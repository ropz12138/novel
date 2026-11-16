"""情节参考子 Agent：按用户动态注册、只读清洗小说并交回章节原文。"""
import asyncio
import json

import pytest

from models.research import ResearchJob, ResearchTextVersion
from models.user import User
from services.agents.supervisor import SupervisorAgent, reset_context, set_context


def _tool_names():
    return {tool.name for tool in SupervisorAgent()._get_tools()}


@pytest.fixture
def uploaded_novels(db_session, tmp_path):
    owner = User(username="reference-owner", email="reference-owner@test.local", password_hash="x")
    stranger = User(username="reference-other", email="reference-other@test.local", password_hash="x")
    db_session.add_all([owner, stranger])
    db_session.flush()

    def create(user, filename, suffix):
        text = f"第一章 烟火气{suffix}\n众人围桌吃面，争论谁来洗碗。\n第二章 夜袭{suffix}\n钟声骤响，众人拔刀迎敌。"
        text_path = tmp_path / f"{suffix}.txt"
        text_path.write_text(text, encoding="utf-8")
        second = text.index("第二章")
        index = [
            {"type": "chapter", "number": 1, "title": "烟火气", "heading": f"第一章 烟火气{suffix}",
             "char_start": 0, "char_end": second},
            {"type": "chapter", "number": 2, "title": "夜袭", "heading": f"第二章 夜袭{suffix}",
             "char_start": second, "char_end": len(text)},
        ]
        index_path = tmp_path / f"{suffix}.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        job = ResearchJob(user_id=user.id, original_filename=filename, status="ready", stage="已清洗")
        db_session.add(job)
        db_session.flush()
        version = ResearchTextVersion(job_id=job.id, version_number=1, kind="cleaned", encoding="utf-8",
                                      file_path=str(text_path), index_path=str(index_path), sha256=suffix * 64)
        db_session.add(version)
        db_session.flush()
        job.active_version_id = version.id
        return job, version

    owned = create(owner, "生活样本.txt", "a")
    foreign = create(stranger, "他人小说.txt", "b")
    db_session.commit()
    return owner, stranger, owned, foreign


def test_reference_agent_is_registered_only_for_user_with_uploaded_novels(uploaded_novels):
    owner, stranger, _, _ = uploaded_novels
    token = set_context({"user_id": owner.id})
    try:
        assert "run_reference_agent" in _tool_names()
    finally:
        reset_context(token)

    empty = User(username="reference-empty", email="reference-empty@test.local", password_hash="x")
    from database import SessionLocal
    with SessionLocal() as db:
        db.add(empty)
        db.commit()
        db.refresh(empty)
        empty_id = empty.id
    token = set_context({"user_id": empty_id})
    try:
        assert "run_reference_agent" not in _tool_names()
    finally:
        reset_context(token)

    assert "run_reference_agent" not in _tool_names()


def test_reference_agent_prompt_lists_current_user_searchable_novels(uploaded_novels, db_session, tmp_path):
    owner, stranger, (owned, _), (foreign, _) = uploaded_novels
    text = "第一章 城门\n守军换岗。"
    text_path = tmp_path / "dark-age.txt"
    text_path.write_text(text, encoding="utf-8")
    index_path = tmp_path / "dark-age.json"
    index_path.write_text(json.dumps([
        {"type": "chapter", "number": 1, "title": "城门", "heading": "第一章 城门",
         "char_start": 0, "char_end": len(text)},
    ], ensure_ascii=False), encoding="utf-8")
    second = ResearchJob(user_id=owner.id, original_filename="黑暗纪元.txt", status="completed", stage="分析完成")
    db_session.add(second)
    db_session.flush()
    version = ResearchTextVersion(
        job_id=second.id, version_number=1, kind="cleaned", encoding="utf-8",
        file_path=str(text_path), index_path=str(index_path), sha256="c" * 64,
    )
    db_session.add(version)
    db_session.flush()
    second.active_version_id = version.id
    uncleaned = ResearchJob(user_id=owner.id, original_filename="未清洗.txt", status="queued", stage="准备文件")
    db_session.add(uncleaned)
    db_session.commit()

    def description_for(user_id):
        token = set_context({"user_id": user_id})
        try:
            tool = next(tool for tool in SupervisorAgent()._get_tools() if tool.name == "run_reference_agent")
            return tool.description
        finally:
            reset_context(token)

    owner_prompt = description_for(owner.id)
    assert f"{owned.original_filename} {owned.id}" in owner_prompt
    assert f"黑暗纪元.txt {second.id}" in owner_prompt
    assert foreign.original_filename not in owner_prompt
    assert foreign.id not in owner_prompt
    assert uncleaned.original_filename not in owner_prompt
    assert uncleaned.id not in owner_prompt

    stranger_prompt = description_for(stranger.id)
    assert f"{foreign.original_filename} {foreign.id}" in stranger_prompt
    assert owned.id not in stranger_prompt
    assert second.id not in stranger_prompt


def test_reference_catalog_search_and_full_chapter_read_are_owner_scoped(uploaded_novels):
    owner, _, (job, version), (_, foreign_version) = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    token = set_context({"user_id": owner.id})
    try:
        catalog = json.loads(module._list_reference_chapters_sync([job.id]))
        assert [item["heading"] for item in catalog["chapters"]] == ["第一章 烟火气a", "第二章 夜袭a"]

        hits = json.loads(module._search_reference_chapters_sync([job.id], ["吃面", "洗碗"]))
        assert hits["matches"] == [{
            "work_id": job.id, "source_filename": "生活样本.txt", "version_id": version.id,
            "section_index": 0, "heading": "第一章 烟火气a", "matched_terms": ["吃面", "洗碗"],
        }]

        chapter = json.loads(module._read_reference_chapters_sync([
            {"version_id": version.id, "section_index": 0},
        ]))
        assert chapter["chapters"][0]["content"].endswith("众人围桌吃面，争论谁来洗碗。")

        with pytest.raises(ValueError, match="当前用户"):
            module._read_reference_chapters_sync([
                {"version_id": foreign_version.id, "section_index": 0},
            ])
    finally:
        reset_context(token)


def test_reference_agent_returns_retrieved_chapter_text(uploaded_novels, monkeypatch):
    owner, _, (job, version), _ = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    async def fake_invoke(*, task, allowed_work_ids, child_task=None):
        assert task["planning_need"] == "主线太密，需要轻松日常"
        assert task["available_works"] == [{"work_id": job.id, "source_filename": "生活样本.txt"}]
        assert allowed_work_ids == {job.id}
        return {
            "text": "第一章 烟火气a\n众人围桌吃面，争论谁来洗碗。",
            "sources": [{"work_id": job.id, "version_id": version.id,
                         "section_index": 0, "heading": "第一章 烟火气a"}],
        }

    monkeypatch.setattr(module, "_invoke_reference_agent", fake_invoke)
    token = set_context({"user_id": owner.id})
    try:
        tool = next(tool for tool in SupervisorAgent()._get_tools() if tool.name == "run_reference_agent")
        result = invoke_reference(tool, {
            "planning_need": "主线太密，需要轻松日常",
            "current_story_context": "队伍刚结束连续追杀，成员关系紧绷。",
            "desired_experience": "轻松、搞笑、关系升温",
            "research_work_ids": [job.id],
            "candidate_count": 3,
        })
    finally:
        reset_context(token)

    assert result["success"]
    assert result["text"].endswith("众人围桌吃面，争论谁来洗碗。")
    assert result["sources"][0]["section_index"] == 0
    assert "candidates" not in result


def test_reference_agent_rejects_foreign_work_before_invocation(uploaded_novels, monkeypatch):
    owner, _, _, (foreign_job, _) = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    async def fail(**kwargs):
        pytest.fail("他人作品不应进入子 Agent")

    monkeypatch.setattr(module, "_invoke_reference_agent", fail)
    token = set_context({"user_id": owner.id})
    try:
        result = invoke_reference(module.run_reference_agent, {
            "planning_need": "找日常事件", "current_story_context": "战后",
            "desired_experience": "轻松", "research_work_ids": [foreign_job.id], "candidate_count": 2,
        })
    finally:
        reset_context(token)
    assert not result["success"]
    assert "当前用户" in result["error"]


@pytest.mark.parametrize('failure', ['malformed_json', 'missing_field', 'wrong_source', 'too_many_chapters', 'analysis_fields'])
def test_reference_submission_retries_in_same_graph_after_error(uploaded_novels, monkeypatch, failure):
    from copy import deepcopy
    from services.agents import llm
    from services.agents.tools import reference_agent_tools as module
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    from services.llm.llm_types import LLMModelConfig

    owner, _, (job, version), _ = uploaded_novels
    source = {'work_id': job.id, 'version_id': version.id, 'section_index': 0}
    valid = {'sources': [source]}
    bad = deepcopy(valid)
    if failure == 'malformed_json':
        bad = {'_raw_arguments': '{"sources":"他说"不行""}'}
    elif failure == 'missing_field':
        bad.pop('sources')
    elif failure == 'wrong_source':
        bad['sources'][0]['section_index'] = 99
    elif failure == 'analysis_fields':
        bad['diagnosis'] = '战后需要低风险互动缓冲。'
    else:
        bad['sources'].append({
            'work_id': job.id, 'version_id': version.id, 'section_index': 1,
        })

    class Provider:
        def __init__(self):
            self.config = LLMModelConfig(name='reference-test', provider='openai',
                                         model='reference-test', base_url='http://example.test', api_key='test')
            self.fallback_config = None
            self.calls = []

        async def stream_chat(self, messages, **kwargs):
            self.calls.append(messages)
            number = len(self.calls)
            if number == 1:
                name = 'read_reference_chapters'
                args = {'chapters': [{'version_id': version.id, 'section_index': 0}]}
            elif number == 2:
                name, args = 'submit_retrieved_chapters', bad
            else:
                assert number == 3, '提交成功后应直接结束'
                assert messages[-1]['role'] == 'tool'
                error = messages[-1]['content']
                if failure in {'malformed_json', 'missing_field'}:
                    assert 'sources' in error
                elif failure == 'wrong_source':
                    assert '章节不存在' in error
                elif failure == 'analysis_fields':
                    assert 'diagnosis' in error
                else:
                    assert '章节数量超过' in error
                assert any(m['role'] == 'tool' and '众人围桌吃面' in str(m['content']) for m in messages)
                name, args = 'submit_retrieved_chapters', valid
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name=name, call_id=f'ref-{number}', arguments=args))

    provider = Provider()
    builds = []
    def get_model(**kwargs):
        builds.append(kwargs)
        model = DeepAgentChatModel(provider=provider, model_name='reference-test')
        model.profile = {'max_input_tokens': 1_000_000}
        return model
    monkeypatch.setattr(llm, 'get_deep_agent_model', get_model)
    token = set_context({'user_id': owner.id})
    try:
        result = invoke_reference(module.run_reference_agent, {
            'planning_need': '找战后缓冲事件', 'current_story_context': '战斗刚结束',
            'desired_experience': '轻松', 'research_work_ids': [job.id], 'candidate_count': 1,
        })
    finally:
        reset_context(token)
    assert result['success'] is True, result
    assert result['sources'] == [{**source, 'heading': '第一章 烟火气a'}]
    assert result['text'] == '第一章 烟火气a\n众人围桌吃面，争论谁来洗碗。'
    assert 'diagnosis' not in result
    assert len(builds) == 1
    assert len(provider.calls) == 3


def test_reference_agent_keeps_parent_session_for_model_headers(monkeypatch):
    from services.agents.supervisor import get_context
    from services.agents.tools.reference_agent_tools import _invoke_reference_agent

    seen = []

    async def fake_subagent(**kwargs):
        seen.append(dict(get_context()))
        raise ValueError("stop")

    monkeypatch.setattr("services.agents.subagent_runtime.invoke_isolated_subagent", fake_subagent)
    token = set_context({
        "user_id": "user-1",
        "work_id": "work-1",
        "session_id": "session-123",
        "model_pref": {"name": "gpt-6-luna-opencode"},
        "history": "父会话秘密",
    })
    try:
        with pytest.raises(ValueError, match="stop"):
            asyncio.run(_invoke_reference_agent(task={"candidate_count": 1}, allowed_work_ids={"job-1"}))
    finally:
        reset_context(token)

    assert seen == [{
        "user_id": "user-1",
        "work_id": "work-1",
        "model_pref": {"name": "gpt-6-luna-opencode"},
        "agent_role": "reference_agent",
        "reference_work_ids": frozenset({"job-1"}),
        "session_id": "session-123",
    }]


def test_reference_prompt_retrieves_chapters_without_analysis():
    from services.agents.tools.reference_agent_tools import PROMPT_PATH

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert "submit_retrieved_chapters" in prompt
    assert "日常切片" in prompt
    assert "风物" in prompt
    assert "支线" in prompt
    for removed in (
        "diagnosis", "narrative_function", "reusable_mechanism",
        "adaptation_direction", "selection_guidance", "submit_reference_candidates",
        "叙事机制", "适配方向",
    ):
        assert removed not in prompt


def invoke_reference(tool, args):
    from services.agents.supervisor import get_context
    async def run():
        result = json.loads(await tool.ainvoke(args))
        if result.get('task_id'):
            return await get_context()['run_control'].children[result['task_id']].handle
        return result
    return asyncio.run(run())
