from pathlib import Path
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import inspect

import database as db_module
from models.research import ResearchArtifact, ResearchJob
from models.user import User
from services import research_text_tools as tools
from services import research_agent as research_agent_module


CLASSIFIERS = [
    {
        "name": "volume",
        "pattern": r"^第(?P<number>[一二三四五六七八九十百千0-9]+)卷(?P<title>.*)$",
        "mode": "regex_line",
    },
    {
        "name": "chapter",
        "pattern": r"^第(?P<number>[一二三四五六七八九十百千0-9]+)章(?P<title>.*)$",
        "mode": "regex_line",
    },
    {
        "name": "extra",
        "pattern": r"^番外(?P<number>[一二三四五六七八九十百千0-9]*)(?P<title>.*)$",
        "mode": "regex_line",
    },
]


def _create_user(db_session):
    user = User(
        username="researcher",
        email="research@example.com",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_research_tables_do_not_use_json_columns(db_session):
    columns = []
    inspector = inspect(db_session.bind)
    for table in (
        "research_jobs",
        "research_text_versions",
        "research_events",
        "research_artifacts",
        "research_instructions",
    ):
        columns.extend(inspector.get_columns(table))
    assert all("JSON" not in str(column["type"]).upper() for column in columns)


def test_research_tool_schemas_expose_supported_operations_and_modes():
    built = {
        tool.name: tool
        for tool in research_agent_module.build_research_tools("schema-test")
    }

    inspect_schema = built["inspect_novel_text"].args_schema.model_json_schema()
    assert inspect_schema["properties"]["mode"]["enum"] == [
        "head",
        "tail",
        "head_tail",
        "char_range",
        "evenly_spaced",
    ]

    transform_schema = (
        built["transform_novel_text"].args_schema.model_json_schema()
    )
    transform_rule = transform_schema["$defs"]["TransformRule"]
    assert transform_rule["properties"]["operation"]["enum"] == [
        "delete_line",
        "literal_replace",
        "regex_replace",
        "delete_between",
    ]
    assert transform_rule["properties"]["match_mode"]["enum"] == [
        "literal",
        "contains",
        "regex",
    ]
    assert {"operation", "pattern"} <= set(transform_rule["required"])

    profile_schema = built["get_book_profile"].args_schema.model_json_schema()
    classifier = profile_schema["$defs"]["SectionClassifier"]
    assert classifier["properties"]["mode"]["enum"] == [
        "regex_line",
        "regex_search",
    ]
    assert {"name", "pattern"} <= set(classifier["required"])

    edit_schema = built["edit_novel_text"].args_schema.model_json_schema()
    edit_operation = edit_schema["$defs"]["TextEditOperation"]
    assert edit_operation["properties"]["operation"]["enum"] == [
        "replace",
        "delete",
        "insert_before",
        "insert_after",
    ]

    split_schema = (
        built["split_novel_sections_to_files"].args_schema.model_json_schema()
    )
    assert "{index" in split_schema["properties"]["filename_template"][
        "description"
    ]
    for field in ("section_types", "numbers", "metadata_extractors"):
        assert split_schema["properties"][field]["type"] == "array"
        assert "anyOf" not in split_schema["properties"][field]

    read_sections_schema = (
        built["read_novel_sections"].args_schema.model_json_schema()
    )
    assert read_sections_schema["properties"]["numbers"]["type"] == "array"
    assert "anyOf" not in read_sections_schema["properties"]["numbers"]

    for tool_name in ("read_research_files", "grep_research_files"):
        file_schema = built[tool_name].args_schema.model_json_schema()
        assert file_schema["properties"]["relative_paths"]["type"] == "array"
        assert "anyOf" not in file_schema["properties"]["relative_paths"]

    write_schema = built["write_research_file"].args_schema.model_json_schema()
    assert write_schema["properties"]["mode"]["enum"] == [
        "create",
        "overwrite",
        "append",
    ]


def test_nested_tool_inputs_reach_deterministic_tools_as_plain_dicts(monkeypatch):
    captured = {}

    def fake_transform(job_id, rules, source_version="active", preview=True):
        captured.update({
            "job_id": job_id,
            "rules": rules,
            "source_version": source_version,
            "preview": preview,
        })
        return {"success": True}

    monkeypatch.setattr(tools, "transform_novel_text", fake_transform)
    transform = next(
        tool
        for tool in research_agent_module.build_research_tools("job-typed")
        if tool.name == "transform_novel_text"
    )
    result = transform.invoke({
        "rules": [{
            "id": "remove-ad",
            "operation": "delete_line",
            "pattern": "广告XX",
            "match_mode": "contains",
        }],
        "source_version": "v1",
        "preview": True,
    })

    assert '"success": true' in result
    assert captured["job_id"] == "job-typed"
    assert isinstance(captured["rules"][0], dict)
    assert captured["rules"][0]["operation"] == "delete_line"
    assert captured["rules"][0]["replacement"] == ""


def test_raw_clean_profile_normalize_read_edit_and_diff(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(tools, "RESEARCH_ROOT", tmp_path / "research")
    user = _create_user(db_session)
    source_text = (
        "下载广告XX\r\n"
        "第一卷开端\r\n"
        "内容还在处理中,请稍后重第一章黑夜\r\n"
        "这是第一章正文。\r\n"
        "第二章选择\r\n"
        "这是第二章正文。\r\n"
        "第三章终局\r\n"
        "这是第三章正文。\r\n"
        "番外一后来\r\n"
        "这是番外正文。\r\n"
        "下载广告XX\r\n"
    )
    raw = source_text.encode("gb18030")
    created = tools.create_job_files(user.id, "样例.txt", raw)
    job_id = created["job_id"]

    inspected = tools.inspect_novel_text(
        job_id, mode="head_tail", window_chars=300,
    )
    assert inspected["encoding"] == "gb18030"
    assert len(inspected["samples"]) == 2

    grep = tools.grep_novel_text(
        job_id, query="下载广告XX", version="original",
    )
    assert grep["total_matches"] == 2

    copied = tools.create_cleaned_copy(
        job_id, source_encoding="gb18030",
    )
    assert copied["version_number"] == 1

    rules = [
        {
            "id": "remove_ad",
            "operation": "delete_line",
            "match_mode": "literal",
            "pattern": "下载广告XX",
        },
        {
            "id": "repair_heading",
            "operation": "regex_replace",
            "pattern": r"内容还在处理中,请稍后重(?P<heading>第[^\n]+章[^\n]*)",
            "replacement": "${heading}",
        },
    ]
    preview = tools.transform_novel_text(job_id, rules, preview=True)
    assert preview["rules"][0]["matches"] == 2
    assert preview["rules"][1]["matches"] == 1
    transformed = tools.transform_novel_text(job_id, rules, preview=False)

    profile = tools.get_book_profile(job_id, CLASSIFIERS)
    assert profile["categories"]["chapter"]["count"] == 3
    assert profile["categories"]["extra"]["count"] == 1

    normalized = tools.normalize_novel_sections(job_id, CLASSIFIERS)
    assert normalized["profile"]["categories"]["chapter"]["count"] == 3
    assert Path(normalized["index_path"]).is_file()

    split = tools.split_novel_sections_to_files(
        job_id,
        section_types=["chapter", "extra"],
        target_directory="chapters",
    )
    assert split["file_count"] == 4
    assert Path(
        tmp_path / "research" / job_id / "workspace" / split["manifest_path"]
    ).is_file()
    split_paths = [item["path"] for item in split["files"]]
    assert len(set(split_paths)) == 4

    index_path = Path(normalized["index_path"])
    original_index = json.loads(index_path.read_text(encoding="utf-8"))
    incomplete_index = json.loads(json.dumps(original_index, ensure_ascii=False))
    for section in incomplete_index:
        section["number"] = None
        section["number_raw"] = None
        section["title"] = ""
    index_path.write_text(
        json.dumps(incomplete_index, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        extracted = tools.split_novel_sections_to_files(
            job_id,
            section_types=["chapter"],
            target_directory="chapters-extracted",
            filename_template="{index:04d}-ch-{number}-{title}.txt",
            metadata_extractors=CLASSIFIERS,
        )
        assert extracted["file_count"] == 3
        assert any(
            "ch-1-黑夜.txt" in item["path"]
            for item in extracted["files"]
        )
        old_extracted_paths = [item["path"] for item in extracted["files"]]
        rebuilt = tools.split_novel_sections_to_files(
            job_id,
            section_types=["chapter"],
            target_directory="chapters-extracted",
            filename_template="renamed-{index:04d}-{number}.txt",
            metadata_extractors=CLASSIFIERS,
            overwrite=True,
        )
        assert rebuilt["file_count"] == 3
        workspace = tmp_path / "research" / job_id / "workspace"
        assert all(not (workspace / path).exists() for path in old_extracted_paths)
        assert all((workspace / item["path"]).is_file() for item in rebuilt["files"])
    finally:
        index_path.write_text(
            json.dumps(original_index, ensure_ascii=False),
            encoding="utf-8",
        )

    listed = tools.list_research_files(
        job_id,
        relative_path="chapters",
        glob_pattern="*.txt",
    )
    assert listed["total"] == 4

    file_read = tools.read_research_files(
        job_id,
        relative_paths=split_paths[:2],
        max_chars_per_file=10_000,
    )
    assert file_read["read_files"] == 2
    assert "正文" in file_read["files"][0]["content"]

    file_grep = tools.grep_research_files(
        job_id,
        query="第二章正文",
        relative_paths=split_paths,
    )
    assert file_grep["total_matches"] == 1
    assert file_grep["matched_files"] == 1
    assert file_grep["matches"][0]["path"] in split_paths

    directory = tools.create_research_directory(
        job_id,
        relative_path="notes/characters",
    )
    assert directory["path"] == "notes/characters"
    written = tools.write_research_file(
        job_id,
        relative_path="notes/characters/叶默.md",
        content="# 叶默\n",
    )
    assert written["mode"] == "create"
    tools.write_research_file(
        job_id,
        relative_path="notes/characters/叶默.md",
        content="主角\n",
        mode="append",
    )
    note = tools.read_research_files(
        job_id,
        relative_paths=["notes/characters/叶默.md"],
    )
    assert note["files"][0]["content"] == "# 叶默\n主角\n"
    with pytest.raises(ValueError, match="安全的相对路径"):
        tools.read_research_files(job_id, relative_paths=["../original/样例.txt"])

    read = tools.read_novel_sections(
        job_id,
        section_type="chapter",
        start_number=1,
        end_number=2,
        max_chars=10_000,
    )
    assert read["selected_count"] == 2
    assert "第一章正文" in read["sections"][0]["text"]

    edit_preview = tools.edit_novel_text(
        job_id,
        operations=[{
            "operation": "replace",
            "expected_text": "这是第二章正文。",
            "new_text": "这是第二章整理后的正文。",
        }],
        preview=True,
    )
    assert "第二章整理后的正文" in edit_preview["diff"]
    edited = tools.edit_novel_text(
        job_id,
        operations=[{
            "operation": "replace",
            "expected_text": "这是第二章正文。",
            "new_text": "这是第二章整理后的正文。",
        }],
        preview=False,
    )
    diff = tools.diff_novel_versions(
        job_id,
        old_version=normalized["version_id"],
        new_version=edited["version_id"],
    )
    assert diff["replaced_lines"] >= 1

    original_path = Path(
        tools.inspect_novel_text(job_id, version="original")["samples"][0]["text"]
        and (tmp_path / "research" / job_id / "original" / "样例.txt")
    )
    assert original_path.read_bytes() == raw


def test_independent_agent_runs_until_complete_without_iteration_limit(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(tools, "RESEARCH_ROOT", tmp_path / "research")
    user = _create_user(db_session)
    created = tools.create_job_files(
        user.id,
        "short.txt",
        "第一章 开始\n正文".encode(),
    )
    job_id = created["job_id"]

    responses = [
        AIMessage(
            content="先保存最终报告",
            tool_calls=[{
                "id": "call-1",
                "name": "save_research_artifact",
                "args": {
                    "artifact_type": "final_report",
                    "title": "完整报告",
                    "content": "已完成这个测试文件的分析。",
                    "metadata_text": "覆盖第一章",
                },
            }],
        ),
        AIMessage(
            content="完成",
            tool_calls=[{
                "id": "call-2",
                "name": "complete_research",
                "args": {"summary": "完整覆盖测试文件"},
            }],
        ),
    ]

    class FakeLLM:
        async def ainvoke(self, _messages):
            return responses.pop(0)

    fake = FakeLLM()
    monkeypatch.setattr(research_agent_module, "get_llm", lambda **_kwargs: fake)
    monkeypatch.setattr(
        research_agent_module,
        "bind_tools_to_llm",
        lambda _llm, _tools: fake,
    )

    manager = research_agent_module.ResearchAgentManager()
    asyncio.run(manager._run(job_id))

    db = db_module.SessionLocal()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).one()
        assert job.status == "completed"
        assert db.query(ResearchArtifact).filter(
            ResearchArtifact.job_id == job_id,
            ResearchArtifact.artifact_type == "final_report",
        ).count() == 1
    finally:
        db.close()
