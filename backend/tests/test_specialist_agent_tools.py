import asyncio
import importlib
import json

from langchain_core.messages import AIMessage

import database
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork


sat = importlib.import_module("services.agents.tools.specialist_agent_tools")
llm_mod = importlib.import_module("services.agents.llm")


class FakeLLM:
    def __init__(self, captured, payload):
        self.captured = captured
        self.payload = payload

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        self.captured["kwargs"] = kwargs
        return AIMessage(content=json.dumps(self.payload, ensure_ascii=False))


class StreamingFakeLLM:
    def __init__(self, chunks):
        self.chunks = chunks

    async def astream(self, messages, config=None, **kwargs):
        from langchain_core.messages import AIMessageChunk
        for chunk in self.chunks:
            yield AIMessageChunk(content=chunk)


def test_json_agent_streams_decoded_content_field(monkeypatch):
    chunks = ['{"content":"第一', '段\\n第二', '段","ok":true}']
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: StreamingFakeLLM(chunks))
    deltas = []

    async def collect(delta):
        deltas.append(delta)

    result = asyncio.run(sat._invoke_json_agent(
        "chapter_writer.txt",
        "上下文",
        content_delta_callback=collect,
    ))

    assert result["content"] == "第一段\n第二段"
    assert "".join(deltas) == "第一段\n第二段"


def _work(db):
    user = User(username="specialist", email="specialist@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="测试作品")
    db.add(work)
    db.commit()
    return work


def _node(db, work_id, node_type, title, content, sort_order):
    node = Node(
        work_id=work_id,
        type=node_type,
        title=title,
        content=content,
        sort_order=sort_order,
    )
    db.add(node)
    db.commit()
    return node


def test_specialist_tools_are_registered_on_supervisor():
    from services.agents.supervisor import SupervisorAgent

    names = {tool.name for tool in SupervisorAgent()._get_tools()}
    assert {
        "load_write_chapter_skill",
        "assemble_chapter_context",
        "plan_chapter_scenes",
        "prepare_chapter_from_scene_plan",
        "write_chapter_draft",
        "review_chapter_continuity",
        "review_chapter_dialogue",
        "revise_chapter_draft",
        "decide_chapter_revision",
        "replan_chapter_scenes",
        "rewrite_chapter_draft",
        "edit_chapter_draft_locally",
        "summarize_chapter_draft",
        "commit_chapter_workflow_result",
    } <= names


def test_prepare_chapter_from_scene_plan_updates_metadata_without_changing_content(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        chapter = _node(db, work.id, "chapter", "第一章", "用户原正文", 1)
        character = _node(db, work.id, "character", "林川", "角色设定", 1)
        work_id, chapter_id, character_id = work.id, chapter.id, character.id
    finally:
        db.close()
    plan = sat._create_artifact(
        work_id,
        chapter_id,
        "scene_plan",
        json.dumps({
            "scenes": [{
                "order": 1,
                "title": "敲门",
                "purpose": "确认来客身份",
                "characters": ["林川"],
                "beats": [{"action": "开门", "dialogue_purpose": "试探"}],
            }],
        }, ensure_ascii=False),
    )

    result = json.loads(asyncio.run(sat.prepare_chapter_from_scene_plan.ainvoke({
        "chapter_node_id": chapter_id,
        "scene_plan_artifact_id": plan.id,
        "character_node_ids": [character_id],
    })))

    assert result["gate"] == {"passed": True, "code": "chapter_structure_prepared"}
    assert result["result"]["content_unchanged"] is True
    db = database.SessionLocal()
    try:
        saved = db.query(Node).filter(Node.id == chapter_id).one()
        assert saved.content == "用户原正文"
        assert saved.extra_data["chapter_elements"] == [{
            "title": "敲门",
            "content": "确认来客身份",
        }]
        assert saved.extra_data["characters"] == [{"id": character_id, "name": "林川"}]
    finally:
        db.close()


def test_load_write_chapter_skill_returns_full_skill():
    result = json.loads(asyncio.run(sat.load_write_chapter_skill.ainvoke({})))

    assert result["success"] is True
    assert result["status"] == "completed"
    assert "场景规划" in result["result"]["skill_content"]
    assert "对白审查" in result["result"]["skill_content"]
    assert result["gate"]["code"] == "workflow_skill_loaded"


def test_assemble_context_persists_full_text_artifact(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        _node(db, work.id, "worldbuilding", "世界", "完整世界设定", 1)
        _node(db, work.id, "character", "林川", "谨慎，回答简短", 1)
        previous = _node(db, work.id, "chapter", "第一章", "上一章完整正文。门外响起敲门声。", 1)
        current = _node(db, work.id, "chapter", "第二章", "", 2)
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work.id)

        result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
            "chapter_node_id": current.id,
            "user_instruction": "承接敲门声",
            "target_words": 3000,
        })))

        assert result["success"] is True
        assert result["gate"]["passed"] is True
        assert result["result"]["previous_chapter"]["node_id"] == previous.id
        assert len(result["result"]["source_content_sha256"]) == 64
        artifact = sat._load_artifact(result["artifact"]["id"])
        assert "完整世界设定" in artifact.content
        assert "上一章完整正文" in artifact.content
        assert "谨慎，回答简短" in artifact.content
        assert "承接敲门声" in artifact.content
        assert result["result"]["chapter_created"] is False
    finally:
        db.close()


def test_assemble_creates_chapter_under_plot_with_contains_edge(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        plot = _node(db, work.id, "plot", "末日初临", "情节正文", 1)
        _node(db, work.id, "worldbuilding", "世界", "完整世界设定", 1)
        work_id, plot_id = work.id, plot.id
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work_id)
    finally:
        db.close()

    result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
        "parent_node_id": plot_id,
        "chapter_title": "第一章：末日降临",
        "sort_order": 1,
        "user_instruction": "写第一章",
        "target_words": 3000,
    })))

    assert result["success"] is True, json.dumps(result, ensure_ascii=False)
    assert result["gate"]["passed"] is True
    assert result["result"]["chapter_created"] is True
    assert result["result"]["chapter_title"] == "第一章：末日降临"
    assert result["result"]["parent_node_id"] == plot_id
    chapter_id = result["result"]["chapter_node_id"]
    db = database.SessionLocal()
    try:
        chapter = db.query(Node).filter(Node.id == chapter_id).one()
        assert chapter.type == "chapter"
        assert chapter.title == "第一章：末日降临"
        assert chapter.sort_order == 1
        assert chapter.content == ""
        edge = db.query(Edge).filter(Edge.work_id == work_id).one()
        assert edge.source_id == plot_id
        assert edge.target_id == chapter_id
        assert edge.edge_type == "contains"
        artifact = sat._load_artifact(result["artifact"]["id"])
        assert "完整世界设定" in artifact.content
        assert "写第一章" in artifact.content
        assert "第一章：末日降临" in artifact.content
    finally:
        db.close()


def test_assemble_rejects_mixed_existing_and_create_params(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        plot = _node(db, work.id, "plot", "情节", "情节", 1)
        chapter = _node(db, work.id, "chapter", "第一章", "", 1)
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work.id)

        result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
            "chapter_node_id": chapter.id,
            "parent_node_id": plot.id,
            "chapter_title": "第一章",
            "sort_order": 1,
        })))

        assert result["success"] is False
        assert result["gate"]["code"] == "chapter_context_mode_conflict"
    finally:
        db.close()


def test_assemble_rejects_missing_target():
    result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
        "user_instruction": "写第一章",
    })))

    assert result["success"] is False
    assert result["gate"]["code"] == "chapter_context_target_required"


def test_assemble_rejects_incomplete_create_params(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        plot = _node(db, work.id, "plot", "情节", "情节", 1)
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work.id)

        result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
            "parent_node_id": plot.id,
        })))

        assert result["success"] is False
        assert result["gate"]["code"] == "chapter_create_params_incomplete"
    finally:
        db.close()


def test_assemble_rejects_non_plot_parent(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        volume = _node(db, work.id, "volume", "第一卷", "卷", 1)
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work.id)

        result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
            "parent_node_id": volume.id,
            "chapter_title": "第一章",
            "sort_order": 1,
        })))

        assert result["success"] is False
        assert result["gate"]["code"] == "invalid_parent_type"
        assert db.query(Node).filter(Node.work_id == work.id, Node.type == "chapter").count() == 0
        assert db.query(Edge).filter(Edge.work_id == work.id).count() == 0
    finally:
        db.close()


def test_assemble_rejects_missing_parent(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _work(db)
        monkeypatch.setattr(sat, "_get_current_work_id", lambda: work.id)

        result = json.loads(asyncio.run(sat.assemble_chapter_context.ainvoke({
            "parent_node_id": "missing-plot-id",
            "chapter_title": "第一章",
            "sort_order": 1,
        })))

        assert result["success"] is False
        assert result["gate"]["code"] == "parent_node_not_found"
    finally:
        db.close()


def test_load_write_chapter_skill_documents_assemble_create_mode():
    result = json.loads(asyncio.run(sat.load_write_chapter_skill.ainvoke({})))
    skill = result["result"]["skill_content"]
    assert "parent_node_id" in skill
    assert "chapter_title" in skill
    assert "两组参数互斥" in skill
    assert "contains" in skill


def test_scene_plan_agent_uses_project_llm_and_returns_artifact(monkeypatch):
    context = sat._create_artifact(
        work_id=None,
        chapter_node_id=None,
        artifact_type="chapter_context",
        content="不应被截断的完整上下文末尾标记：END-CONTEXT",
    )
    captured = {}
    payload = {
        "chapter_goal": "确认来客身份",
        "opening_carryover": "承接敲门声",
        "emotional_progression": "戒备到怀疑",
        "scenes": [{
            "order": 1,
            "title": "开门",
            "setting": "深夜门口",
            "purpose": "试探",
            "characters": ["林川"],
            "approximate_words": 3000,
            "beats": [{"action": "开门", "dialogue_purpose": "确认身份", "speaker_intention": "试探", "listener_reaction": "回避"}],
            "emotional_shift": "戒备加深",
            "information_change": "确认来客认识自己",
        }],
        "ending_hook": "伞上没有雨水",
    }
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM(captured, payload))

    result = json.loads(asyncio.run(sat.plan_chapter_scenes.ainvoke({
        "context_artifact_id": context.id,
    })))

    assert result["success"] is True
    assert result["artifact"]["type"] == "scene_plan"
    assert result["result"]["scene_count"] == 1
    assert "END-CONTEXT" in captured["messages"][-1].content
    assert "max_tokens" not in captured["kwargs"]


def test_short_chapter_draft_requires_revision(monkeypatch):
    context = sat._create_artifact(
        None,
        None,
        "chapter_context",
        json.dumps({"target_words": 3000}, ensure_ascii=False),
    )
    plan = sat._create_artifact(None, None, "scene_plan", json.dumps({"scenes": []}))
    responses = iter([
        {"content": "短" * 1257, "scene_coverage": [], "completion": {}},
        {"advice": "补足中段场景与人物对话。"},
    ])
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, next(responses)))

    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
    })))

    assert result["success"] is True
    assert result["status"] == "needs_revision"
    assert result["gate"] == {"passed": False, "code": "draft_length_revision_required"}
    assert result["result"]["minimum_words"] == 2550
    assert result["result"]["missing_words"] == 1293
    assert result["result"]["feedback"] == (
        "章节初稿共1257字，目标3000字，允许范围2550—3450字；"
        "低于下限1293字。请在修订时补足正文至允许范围。"
    )


def test_chapter_draft_writes_existing_node_before_workflow_commit(db_session, monkeypatch):
    work = _work(db_session)
    chapter = _node(db_session, work.id, "chapter", "第一章", "原正文", 1)
    context = sat._create_artifact(
        work.id, chapter.id, "chapter_context",
        json.dumps({"target_words": 0, "target_chapter": {"title": chapter.title, "content": "原正文"}}, ensure_ascii=False),
    )
    plan = sat._create_artifact(work.id, chapter.id, "scene_plan", json.dumps({"scenes": []}))
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {"content": "新正文", "scene_coverage": []}))

    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id, "scene_plan_artifact_id": plan.id,
    })))

    assert result["success"] is True
    db_session.refresh(chapter)
    assert chapter.content == "新正文"

    commit = json.loads(asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
        "chapter_node_id": chapter.id,
        "draft_artifact_id": result["artifact"]["id"],
        "expected_content_sha256": sat._content_sha256("原正文"),
    })))
    assert commit["success"] is True
    assert commit["status"] == "completed"


def test_long_chapter_draft_returns_natural_language_length_feedback(monkeypatch):
    context = sat._create_artifact(
        None, None, "chapter_context", json.dumps({"target_words": 3000})
    )
    plan = sat._create_artifact(None, None, "scene_plan", json.dumps({"scenes": []}))
    responses = iter([
        {"content": "长" * 4052, "scene_coverage": [], "completion": {}},
        {"advice": "精简重复的环境描写。"},
    ])
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, next(responses)))

    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
    })))

    assert result["status"] == "needs_revision"
    assert result["result"]["excess_words"] == 602
    assert result["result"]["feedback"] == (
        "章节初稿共4052字，目标3000字，允许范围2550—3450字；"
        "超出上限602字。请在修订时精简正文至允许范围。"
    )


def test_out_of_range_chapter_draft_gets_one_internal_llm_advice(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[]}')
    calls = []

    def fake_get_llm(**kwargs):
        payload = (
            {"content": "长" * 4000, "scene_coverage": []}
            if not calls else
            {"advice": "压缩开头的环境描写，保留冲突和章末钩子。"}
        )
        calls.append(payload)
        return FakeLLM({}, payload)

    monkeypatch.setattr(llm_mod, "get_llm", fake_get_llm)
    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
    })))

    assert len(calls) == 2
    assert result["status"] == "needs_revision"
    assert result["result"]["revision_advice"] == "压缩开头的环境描写，保留冲突和章末钩子。"


def test_in_range_chapter_draft_does_not_request_length_advice(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[]}')
    calls = []

    def fake_get_llm(**kwargs):
        calls.append(kwargs)
        return FakeLLM({}, {"content": "正" * 3000, "scene_coverage": []})

    monkeypatch.setattr(llm_mod, "get_llm", fake_get_llm)
    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
    })))

    assert len(calls) == 1
    assert result["status"] == "completed"
    assert "revision_advice" not in result["result"]


def test_chapter_writer_receives_explicit_total_and_scene_word_limits(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", json.dumps({
        "scenes": [
            {"order": 1, "title": "接触联盟", "approximate_words": 1200},
            {"order": 2, "title": "完成任务", "approximate_words": 1800},
        ],
    }, ensure_ascii=False))
    captured = {}
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM(captured, {
        "content": "正" * 3000, "scene_coverage": [],
    }))

    result = json.loads(asyncio.run(sat.write_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
    })))

    assert result["status"] == "completed"
    prompt = captured["messages"][-1].content
    assert "目标字数：3000字" in prompt
    assert "允许范围：2550—3450字" in prompt
    assert "第1场《接触联盟》：约1200字" in prompt
    assert "第2场《完成任务》：约1800字" in prompt


def test_revision_decision_records_selected_strategy(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[]}')
    draft = sat._create_artifact(None, None, "chapter_draft", "第一场。第二场。", parent_artifact_id=plan.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "strategy": "replan",
        "reason": "本章情节跨度过大，适合将第二场移入下一章。",
        "instructions": "本章只保留第一场，第二场作为下一章开端。",
    }))

    result = json.loads(asyncio.run(sat.decide_chapter_revision.ainvoke({
        "context_artifact_id": context.id,
        "scene_plan_artifact_id": plan.id,
        "draft_artifact_id": draft.id,
        "feedback": "初稿超出上限500字",
    })))

    assert result["status"] == "completed"
    assert result["artifact"]["type"] == "chapter_revision_decision"
    assert result["result"]["strategy"] == "replan"
    assert "下一章" in result["result"]["instructions"]


def test_local_chapter_edit_replaces_only_selected_passage(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[]}')
    draft = sat._create_artifact(None, None, "chapter_draft", "开头。冗长的一段。结尾。", parent_artifact_id=plan.id)
    decision = sat._create_artifact(None, None, "chapter_revision_decision", json.dumps({
        "strategy": "local_edit", "reason": "仅一段冗长", "instructions": "压缩中段"
    }), parent_artifact_id=draft.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "replacements": [{"old": "冗长的一段。", "new": "短段。"}],
    }))

    result = json.loads(asyncio.run(sat.edit_chapter_draft_locally.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "decision_artifact_id": decision.id,
    })))

    assert result["status"] == "completed"
    assert result["result"]["word_count_after"] < result["result"]["word_count_before"]
    assert sat._load_artifact(result["artifact"]["id"]).content == "开头。短段。结尾。"


def test_local_chapter_edit_keeps_valid_replacements_when_one_is_missing(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    draft = sat._create_artifact(None, None, "chapter_draft", "开头。冗长的一段。“病毒泄露”结尾。")
    decision = sat._create_artifact(None, None, "chapter_revision_decision", '{"strategy":"local_edit"}', parent_artifact_id=draft.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "replacements": [
            {"old": "冗长的一段。", "new": "短段。"},
            {"old": '"病毒泄露”', "new": "病毒"},
            {"old": "结尾。", "new": "结束。"},
        ],
    }))

    result = json.loads(asyncio.run(sat.edit_chapter_draft_locally.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "decision_artifact_id": decision.id,
    })))

    assert result["status"] == "completed"
    assert result["result"]["replacement_count"] == 2
    assert result["result"]["skipped_replacements"] == [{"old": '"病毒泄露”', "reason": "not_found"}]
    assert result["result"]["feedback"] == '“\"病毒泄露””段在原文中没有找到，其他修改已生效。'
    assert sat._load_artifact(result["artifact"]["id"]).content == "开头。短段。“病毒泄露”结束。"


def test_local_chapter_edit_does_not_save_when_no_replacements_match(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    draft = sat._create_artifact(None, None, "chapter_draft", "原文。")
    decision = sat._create_artifact(None, None, "chapter_revision_decision", '{"strategy":"local_edit"}', parent_artifact_id=draft.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "replacements": [{"old": "不存在。", "new": "替换。"}],
    }))

    result = json.loads(asyncio.run(sat.edit_chapter_draft_locally.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "decision_artifact_id": decision.id,
    })))

    assert result["status"] == "failed"
    assert result["artifact"] is None
    assert "不存在。" in result["error"]["message"]


def test_replan_chapter_scenes_keeps_deferred_scenes(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[{"order":1},{"order":2}]}')
    draft = sat._create_artifact(None, None, "chapter_draft", "第一场。第二场。", parent_artifact_id=plan.id)
    decision = sat._create_artifact(None, None, "chapter_revision_decision", json.dumps({
        "strategy": "replan", "instructions": "只写第一场", "scene_plan_artifact_id": plan.id
    }), parent_artifact_id=draft.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "chapter_goal": "完成第一场", "scenes": [{"order": 1, "title": "第一场"}],
        "ending_hook": "门外传来敲门声", "deferred_scenes": [{"order": 2, "title": "第二场"}],
        "next_chapter_handoff": "下一章从敲门声展开",
    }))

    result = json.loads(asyncio.run(sat.replan_chapter_scenes.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "decision_artifact_id": decision.id,
    })))

    assert result["status"] == "completed"
    assert result["result"]["deferred_scenes"] == [{"order": 2, "title": "第二场"}]
    assert result["artifact"]["type"] == "scene_plan"
    assert result["artifact"]["version"] == 2


def test_rewrite_chapter_draft_creates_full_new_version(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", '{"target_words":3000}')
    plan = sat._create_artifact(None, None, "scene_plan", '{"scenes":[{"order":1}]}')
    draft = sat._create_artifact(None, None, "chapter_draft", "旧稿", parent_artifact_id=plan.id)
    decision = sat._create_artifact(None, None, "chapter_revision_decision", json.dumps({
        "strategy": "rewrite", "instructions": "整章调整叙事视角", "scene_plan_artifact_id": plan.id
    }), parent_artifact_id=draft.id)
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {"content": "完整新稿"}))

    result = json.loads(asyncio.run(sat.rewrite_chapter_draft.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "decision_artifact_id": decision.id,
    })))

    assert result["status"] == "completed"
    assert result["artifact"]["version"] == 2
    assert sat._load_artifact(result["artifact"]["id"]).content == "完整新稿"


def test_commit_rejects_short_draft_even_if_supervisor_skips_length_gate():
    db = database.SessionLocal()
    try:
        work = _work(db)
        chapter = _node(db, work.id, "chapter", "第一章", "", 1)
        work_id, chapter_id = work.id, chapter.id
    finally:
        db.close()
    context = sat._create_artifact(
        work_id,
        chapter_id,
        "chapter_context",
        json.dumps({"target_words": 3000}, ensure_ascii=False),
    )
    plan = sat._create_artifact(
        work_id,
        chapter_id,
        "scene_plan",
        json.dumps({"scenes": []}),
        parent_artifact_id=context.id,
    )
    draft = sat._create_artifact(
        work_id,
        chapter_id,
        "chapter_draft",
        "短" * 1257,
        parent_artifact_id=plan.id,
    )

    result = json.loads(asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
        "chapter_node_id": chapter_id,
        "draft_artifact_id": draft.id,
        "expected_content_sha256": sat._content_sha256(""),
    })))

    assert result["status"] == "needs_revision"
    assert result["gate"] == {"passed": False, "code": "draft_length_revision_required"}
    db = database.SessionLocal()
    try:
        assert db.query(Node).filter(Node.id == chapter_id).one().content == ""
    finally:
        db.close()


def test_review_failure_is_successful_tool_execution(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", "上下文")
    draft = sat._create_artifact(None, None, "chapter_draft", "正文")
    payload = {
        "score": 5,
        "issues": [{
            "id": "dialogue-1",
            "severity": "major",
            "scene_order": 1,
            "characters": ["林川"],
            "excerpt": "我把全部计划告诉你。",
            "issue_type": "intention_too_explicit",
            "problem": "人物表达过于直接",
            "desired_effect": "通过试探传递意图",
            "preserve": ["计划内容不变"],
        }],
        "character_voice": [],
    }
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, payload))

    result = json.loads(asyncio.run(sat.review_chapter_dialogue.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
        "minimum_score": 7,
    })))

    assert result["success"] is True
    assert result["status"] == "needs_revision"
    assert result["gate"] == {
        "passed": False,
        "code": "dialogue_revision_required",
    }
    assert result["result"]["issues"][0]["id"] == "dialogue-1"


def test_moderate_review_issue_requires_revision(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", "上下文")
    draft = sat._create_artifact(None, None, "chapter_draft", "正文")
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "score": 7,
        "issues": [{"id": "d1", "severity": "moderate"}],
        "revision_scope": [{"scene_order": 1, "issue_ids": ["d1"]}],
    }))

    result = json.loads(asyncio.run(sat.review_chapter_dialogue.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
    })))

    assert result["status"] == "needs_revision"


def test_medium_review_issue_requires_revision(monkeypatch):
    context = sat._create_artifact(None, None, "chapter_context", "上下文")
    draft = sat._create_artifact(None, None, "chapter_draft", "正文")
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "score": 8,
        "issues": [{"id": 1, "severity": "medium", "problem": "对白信息揭示过早"}],
    }))

    result = json.loads(asyncio.run(sat.review_chapter_dialogue.ainvoke({
        "context_artifact_id": context.id,
        "draft_artifact_id": draft.id,
    })))

    assert result["status"] == "needs_revision"
    assert result["gate"]["code"] == "dialogue_revision_required"
    assert result["gate"]["passed"] is False


def test_revision_creates_next_draft_version(monkeypatch):
    db = database.SessionLocal()
    work = _work(db)
    chapter = _node(db, work.id, "chapter", "第一章", "", 1)
    work_id, chapter_id = work.id, chapter.id
    db.close()
    draft = sat._create_artifact(work_id, chapter_id, "chapter_draft", "旧稿", version=1)
    review = sat._create_artifact(work_id, chapter_id, "dialogue_review", json.dumps({"issues": []}, ensure_ascii=False))
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: FakeLLM({}, {
        "content": "修改后的完整正文",
        "resolved_issue_ids": ["dialogue-1"],
        "changed_scopes": [{"scene_order": 1, "change_type": "dialogue"}],
        "preservation_check": {"plot_outcome_preserved": True},
    }))

    result = json.loads(asyncio.run(sat.revise_chapter_draft.ainvoke({
        "draft_artifact_id": draft.id,
        "review_artifact_ids": [review.id],
    })))

    assert result["success"] is True
    assert result["artifact"]["version"] == 2
    assert sat._load_artifact(result["artifact"]["id"]).content == "修改后的完整正文"


def test_commit_chapter_saves_latest_draft_and_summary():
    db = database.SessionLocal()
    try:
        work = _work(db)
        chapter = _node(db, work.id, "chapter", "第一章", "旧正文", 1)
        work_id, chapter_id = work.id, chapter.id
        source_content_sha256 = sat._content_sha256(chapter.content)
    finally:
        db.close()
    draft = sat._create_artifact(work_id, chapter_id, "chapter_draft", "最终完整正文", version=2)
    summary = sat._create_artifact(work_id, chapter_id, "chapter_summary", json.dumps({
        "summary": "章节摘要",
        "ending_state": {"location": "车站"},
        "character_changes": [],
        "relation_changes": [],
        "unresolved_threads": [],
    }, ensure_ascii=False))

    result = json.loads(asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
        "chapter_node_id": chapter_id,
        "draft_artifact_id": draft.id,
        "summary_artifact_id": summary.id,
        "expected_content_sha256": source_content_sha256,
    })))

    assert result["success"] is True
    assert result["gate"]["code"] == "chapter_committed"
    db = database.SessionLocal()
    try:
        saved = db.query(Node).filter(Node.id == chapter_id).one()
        assert saved.content == "最终完整正文"
        from models.chapter import Chapter
        chapter_row = db.query(Chapter).filter(Chapter.node_id == chapter_id).one()
        assert chapter_row.summary == "章节摘要"
    finally:
        db.close()


def test_commit_chapter_reports_version_conflict():
    db = database.SessionLocal()
    try:
        work = _work(db)
        chapter = _node(db, work.id, "chapter", "第一章", "用户新正文", 1)
        work_id, chapter_id = work.id, chapter.id
    finally:
        db.close()
    draft = sat._create_artifact(work_id, chapter_id, "chapter_draft", "生成正文")

    result = json.loads(asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
        "chapter_node_id": chapter_id,
        "draft_artifact_id": draft.id,
        "expected_content_sha256": sat._content_sha256("生成前旧正文"),
    })))

    assert result["success"] is True
    assert result["status"] == "needs_user"
    assert result["gate"]["code"] == "chapter_version_conflict"


def test_commit_chapter_records_blocking_gate_in_supervisor_context():
    from services.agents import supervisor as supervisor_mod

    db = database.SessionLocal()
    try:
        work = _work(db)
        chapter = _node(db, work.id, "chapter", "第一章", "已变化正文", 1)
        work_id, chapter_id = work.id, chapter.id
    finally:
        db.close()
    draft = sat._create_artifact(work_id, chapter_id, "chapter_draft", "候选正文")
    supervisor_mod.set_context({"work_id": work_id})
    try:
        asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
            "chapter_node_id": chapter_id,
            "draft_artifact_id": draft.id,
            "expected_content_sha256": sat._content_sha256("原正文"),
        }))
        assert supervisor_mod.get_context()["workflow_gate"] == {
            "passed": False,
            "code": "chapter_version_conflict",
            "status": "needs_user",
        }
    finally:
        supervisor_mod.set_context({})
