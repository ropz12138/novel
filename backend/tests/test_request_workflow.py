"""独立任务清单与需求分析退出后的行为。"""
import asyncio
import json

import pytest
from langchain_core.messages import ToolMessage

from models.chapter import Chapter
from models.node import Node
from models.session import SupervisorMessage, SupervisorSession
from models.user import User
from models.workflow import WorkflowArtifact
from models.work import CanvasWork
from services.agents import supervisor
from services.agents.supervisor import SupervisorAgent
from services.llm.langchain_adapter import DeepAgentChatModel
from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
from services.llm.llm_types import LLMModelConfig
from services.todo_service import list_todo_items, serialize_todo_item


RETIRED = {
    "inspect_work_request",
    "record_request_analysis",
    "verify_work_change",
    "repair_work_change_evidence",
    "rebind_requirement_note",
}
ANALYSIS_TYPES = ("request_analysis", "request_questions", "requirement_binding", "task_completion")


@pytest.fixture
def work_state(db_session):
    user = User(username="requests", email="requests@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="作品")
    db_session.add(work)
    db_session.flush()
    session = SupervisorSession(user_id=user.id, work_id=work.id)
    note = Node(work_id=work.id, type="note", title="写作偏好", content="细节篇幅与叙事价值相称", scope="global", sort_order=1)
    actor = Node(work_id=work.id, type="character", title="陆沉", content="以个人行动争取生存", scope="global", sort_order=1)
    chapter = Node(work_id=work.id, type="chapter", title="第一章", content="清晨出发。", scope="local", sort_order=1)
    db_session.add_all([session, note, actor, chapter])
    db_session.commit()
    token = supervisor.set_context({
        "work_id": work.id,
        "session_id": session.id,
        "user_id": user.id,
        "todo_used_this_turn": False,
        "request_intent": "inquiry",
        "request_analysis_id": "stale-analysis",
        "request_revision": "stale-revision",
    })
    yield work, session, note, actor, chapter
    supervisor.reset_context(token)


def invoke(coro):
    return json.loads(asyncio.run(coro))


def artifact_count(db_session, work_id):
    return db_session.query(WorkflowArtifact).filter(
        WorkflowArtifact.work_id == work_id,
        WorkflowArtifact.artifact_type.in_(ANALYSIS_TYPES),
    ).count()


def test_supervisor_tools_drop_request_registration(work_state):
    names = {tool.name for tool in SupervisorAgent()._get_tools()}
    assert names.isdisjoint(RETIRED)
    for required in ("write_todolist", "read_todolist", "update_todolist", "create_node", "update_node"):
        assert required in names
    assert "record_scene_reasoning" not in names
    assert "humanize_node_content" not in names
    assert "evidence_artifact_id" not in next(
        tool for tool in SupervisorAgent()._get_tools() if tool.name == "update_todolist"
    ).args_schema.model_json_schema()["properties"]


def test_write_todolist_creates_tasks_without_analysis_or_notes(work_state, db_session):
    work, session, note, *_ = work_state
    db_session.add(WorkflowArtifact(
        work_id=work.id, artifact_type="request_analysis",
        content=json.dumps({"session_id": session.id, "task_specs": []}, ensure_ascii=False),
    ))
    db_session.commit()
    before = artifact_count(db_session, work.id)
    message = asyncio.run(__import__(
        "services.agents.tools.todo_tools", fromlist=["_write_todolist_async"]
    )._write_todolist_async(["把第一章的出发时间从清晨改成黄昏"]))
    assert "已创建" in message
    db_session.expire_all()
    assert [item.task for item in list_todo_items(db_session, session.id)] == ["把第一章的出发时间从清晨改成黄昏"]
    assert note.content == "细节篇幅与叙事价值相称"
    assert db_session.query(Node).filter_by(work_id=work.id, type="note").count() == 1
    assert artifact_count(db_session, work.id) == before


def test_todo_crud_matches_rows_and_ignores_analysis(work_state, db_session):
    from services.agents.tools.todo_tools import _read_todolist_async, _update_todolist_async, _write_todolist_async
    _, session, *_ = work_state
    asyncio.run(_write_todolist_async(["修改出发时间", "回读第一章"]))
    assert "已标记完成" in asyncio.run(_update_todolist_async("complete", task_id="T1"))
    edited = asyncio.run(_update_todolist_async("edit", task_id="T2", task="回读第一章"))
    assert "已更新" in edited
    assert "已追加" in asyncio.run(_update_todolist_async("add", tasks=["核对前后情节"]))
    rows = list_todo_items(db_session, session.id)
    assert [item.task_id for item in rows] == ["T1", "T2", "T3"]
    loaded = json.loads(asyncio.run(_read_todolist_async()))
    assert loaded == [serialize_todo_item(item) for item in rows]
    assert all("kind" not in row and "depends_on" not in row for row in loaded)
    assert "已删除" in asyncio.run(_update_todolist_async("remove", task_id="T3"))
    failed = asyncio.run(_update_todolist_async("complete", task_id="T1"))
    assert failed.startswith("失败")
    missing = asyncio.run(_update_todolist_async("complete", task_id="T9"))
    assert missing.startswith("失败")


class ScriptedModel:
    config = LLMModelConfig(name="chosen", base_url="http://test", api_key="test", provider="openai", model="chosen")
    fallback_config = None

    def __init__(self, decide):
        self.decide = decide

    async def stream_chat(self, messages, **kwargs):
        name, call_id, arguments = self.decide(messages)
        yield ToolStreamEvent(kind="tool_call", tool_call=ToolCallFinished(
            tool_name=name, call_id=call_id, arguments=arguments))


def tool_call_names(db_session, session_id):
    return [
        row.content for row in db_session.query(SupervisorMessage)
        .filter_by(session_id=session_id, role="tool_call")
        .order_by(SupervisorMessage.sort_order)
    ]


def install_models(monkeypatch, providers):
    sequence = iter(providers)
    monkeypatch.setattr(
        "services.agents.llm.get_deep_agent_model",
        lambda **kwargs: DeepAgentChatModel(provider=next(sequence), model_name="chosen", profile={"max_input_tokens": 1_000_000}),
    )


def test_one_off_change_reads_updates_and_rereads_without_writer(work_state, db_session, monkeypatch):
    work, session, note, actor, chapter = work_state
    db_session.add(Chapter(work_id=work.id, node_id=chapter.id, title=chapter.title, content=chapter.content, notes=""))
    db_session.commit()

    def one_off(messages):
        last = messages[-1]
        call_id = last.get("tool_call_id")
        if last["role"] != "tool":
            return "write_todolist", "todo", {"tasks": ["把第一章的出发时间从清晨改成黄昏", "回读第一章"]}
        if call_id == "todo":
            return "read_node_content", "read", {"node_ids": [chapter.id]}
        if call_id == "read":
            digest = json.loads(last["content"])["nodes"][0]["content_sha256"]
            return "update_node", "edit", {
                "node_id": chapter.id, "mode": "replace", "expected_content_sha256": digest,
                "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": "黄昏出发。"}],
                "reason": "按作者要求把出发时间改为黄昏",
            }
        if call_id == "edit":
            return "read_node_content", "reread", {"node_ids": [chapter.id]}
        if call_id == "reread":
            return "update_todolist", "complete-1", {"action": "complete", "task_id": "T1"}
        if call_id == "complete-1":
            return "update_todolist", "complete-2", {"action": "complete", "task_id": "T2"}
        return "respond_to_user", "finish", {"message": "第一章已改为黄昏出发。", "outcome": "completed"}

    install_models(monkeypatch, [ScriptedModel(one_off)])
    result = asyncio.run(SupervisorAgent().run("把第一章的出发时间从清晨改成黄昏，其他情节保持不变。", context={
        "work_id": work.id, "session_id": session.id, "user_id": session.user_id,
    }))
    assert result["success"] is True
    db_session.expire_all()
    db_session.refresh(chapter)
    db_session.refresh(note)
    assert chapter.content == "黄昏出发。"
    assert tool_call_names(db_session, session.id) == [
        "write_todolist", "read_node_content", "update_node", "read_node_content",
        "update_todolist", "update_todolist", "respond_to_user",
    ]
    assert "run_writing_agent" not in tool_call_names(db_session, session.id)
    assert note.content == "细节篇幅与叙事价值相称"
    assert db_session.query(Node).filter_by(work_id=work.id, type="note").count() == 1
    assert [item.status for item in list_todo_items(db_session, session.id)] == ["completed", "completed"]

    def failed_write(messages):
        last = messages[-1]
        if last["role"] != "tool":
            return "write_todolist", "todo-fail", {"tasks": ["更新作品长期风格笔记，明确整部作品采用喜剧风格", "依据风格重写第一章"]}
        if last.get("tool_call_id") == "todo-fail":
            return "update_node", "write-fail", {"node_id": chapter.id, "mode": "overwrite", "content": "喜剧开场。"}
        saved = json.loads(last["content"])
        assert saved["success"] is False
        assert saved["error_code"] == "content_hash_required"
        return "respond_to_user", "finish-fail", {"message": "长期笔记尚未保存。", "outcome": "needs_revision"}

    install_models(monkeypatch, [ScriptedModel(failed_write)])
    failed = asyncio.run(SupervisorAgent().run("整部作品以后都采用喜剧风格，先重写第一章。", context={
        "work_id": work.id, "session_id": session.id, "user_id": session.user_id,
    }))
    assert failed["success"] is True
    db_session.expire_all()
    names = tool_call_names(db_session, session.id)
    assert "run_writing_agent" not in names
    assert names[-3:] == ["write_todolist", "update_node", "respond_to_user"]
    assert chapter.content == "黄昏出发。"
    assert db_session.get(SupervisorSession, session.id).status == "needs_revision"
    assert db_session.query(Node).filter_by(work_id=work.id, type="note").count() == 1
    assert {item.task_id: item.status for item in list_todo_items(db_session, session.id)}["T1"] == "pending"


def test_wrong_paragraph_is_corrected_from_the_latest_read(work_state, db_session, monkeypatch):
    work, session, _, actor, _ = work_state
    actor.content = "清晨赶路。\n\n夜里休息。"
    db_session.commit()
    before = artifact_count(db_session, work.id)
    used = []

    def correct(messages):
        last = messages[-1]
        call_id = last.get("tool_call_id")
        if last["role"] != "tool":
            return "write_todolist", "todo", {"tasks": ["把角色清晨赶路改成黄昏赶路"]}
        if call_id == "todo":
            return "read_node_content", "read-1", {"node_ids": [actor.id]}
        if call_id == "complete":
            return "respond_to_user", "finish", {"message": "角色设定已改为黄昏赶路。", "outcome": "completed"}
        saved = json.loads(last["content"])
        if call_id == "read-1":
            digest = saved["nodes"][0]["content_sha256"]
            used.append(digest)
            return "update_node", "wrong", {
                "node_id": actor.id, "mode": "replace", "expected_content_sha256": digest,
                "replacements": [{"start_paragraph": 2, "end_paragraph": 2, "new": "夜里赶路。"}],
            }
        if call_id == "wrong":
            assert saved["success"] is True
            return "read_node_content", "read-2", {"node_ids": [actor.id]}
        if call_id == "read-2":
            paragraphs = saved["nodes"][0]["content_paragraphs"]
            assert [item["text"] for item in paragraphs] == ["清晨赶路。", "夜里赶路。"]
            digest = saved["nodes"][0]["content_sha256"]
            assert digest != used[0]
            used.append(digest)
            return "update_node", "fix", {
                "node_id": actor.id, "mode": "replace", "expected_content_sha256": digest,
                "replacements": [
                    {"start_paragraph": 1, "end_paragraph": 1, "new": "黄昏赶路。"},
                    {"start_paragraph": 2, "end_paragraph": 2, "new": "夜里休息。"},
                ],
            }
        if call_id == "fix":
            assert saved["success"] is True
            return "read_node_content", "read-3", {"node_ids": [actor.id]}
        if call_id == "read-3":
            assert [item["text"] for item in saved["nodes"][0]["content_paragraphs"]] == ["黄昏赶路。", "夜里休息。"]
            return "update_todolist", "complete", {"action": "complete", "task_id": "T1"}
        return "respond_to_user", "finish", {"message": "角色设定已改为黄昏赶路。", "outcome": "completed"}

    install_models(monkeypatch, [ScriptedModel(correct)])
    result = asyncio.run(SupervisorAgent().run("把陆沉的清晨赶路改成黄昏赶路。", context={
        "work_id": work.id, "session_id": session.id, "user_id": session.user_id,
    }))
    assert result["success"] is True
    db_session.expire_all()
    db_session.refresh(actor)
    assert actor.content == "黄昏赶路。\n\n夜里休息。"
    names = tool_call_names(db_session, session.id)
    assert names == [
        "write_todolist", "read_node_content", "update_node", "read_node_content",
        "update_node", "read_node_content", "update_todolist", "respond_to_user",
    ]
    assert "run_review_agent" not in names
    assert artifact_count(db_session, work.id) == before
    assert list_todo_items(db_session, session.id)[0].status == "completed"


def test_historical_inquiry_artifact_does_not_block_a_new_change(work_state, db_session):
    work, session, note, actor, _ = work_state
    db_session.add(WorkflowArtifact(
        work_id=work.id, artifact_type="request_context",
        content=json.dumps({"session_id": session.id, "request_intent": "inquiry", "user_instruction": "为什么这里还是霸道血气？"}, ensure_ascii=False),
    ))
    db_session.commit()
    from services.agents.tools.supervisor_node_tools import supervisor_node_tools
    update = next(tool for tool in supervisor_node_tools if tool.name == "update_node")
    saved = invoke(update.ainvoke({"node_id": actor.id, "content": "能力名称为丧尸化能力"}))
    assert saved["success"] is True
    db_session.refresh(actor)
    assert actor.content == "能力名称为丧尸化能力"
    db_session.refresh(note)
    assert note.content == "细节篇幅与叙事价值相称"


def test_delivery_follows_this_turn_todo_participation(work_state, db_session):
    from services.agents.deep_agent_runtime import RequireToolCallMiddleware
    from services.agents.tools.respond_to_user_tool import _respond_and_complete, _respond_to_user
    from services.agents.tools.todo_tools import _read_todolist_async, _write_todolist_async
    ctx = supervisor.get_context()

    direct = json.loads(asyncio.run(_respond_and_complete("正文仍写的是霸道血气。", outcome="completed")))
    synced = json.loads(_respond_to_user("正文仍写的是霸道血气。", outcome="completed"))
    assert direct["success"] is True and direct["status"] == "completed"
    assert synced == direct
    assert ctx["workflow_gate"]["status"] == "completed"

    asyncio.run(_write_todolist_async(["保存第三人称有限视角", "回读笔记"]))
    assert ctx["todo_used_this_turn"] is True

    async def blocked():
        failed = json.loads(await _respond_and_complete("都做完了。", outcome="completed"))
        waiting = json.loads(await _respond_and_complete("请确认视角范围。", outcome="needs_user"))
        partial = json.loads(await _respond_and_complete("笔记尚未保存。", outcome="needs_revision"))
        return failed, waiting, partial

    failed, waiting, partial = asyncio.run(blocked())
    unknown = json.loads(_respond_to_user("完成。", completed_task_ids=["T9"], outcome="completed"))

    assert failed["success"] is False and failed["status"] == "needs_revision"
    assert [item["task_id"] for item in failed["pending_tasks"]] == ["T1", "T2"]
    assert waiting["success"] is True and waiting["status"] == "needs_user"
    assert partial["success"] is True and partial["status"] == "needs_revision"
    assert unknown["success"] is False
    assert unknown["task_completion_errors"]

    async def resume_old_list():
        ctx["todo_used_this_turn"] = False
        quiet = json.loads(await _respond_and_complete("只回答事实。", outcome="completed"))
        await _read_todolist_async()
        resumed = json.loads(await _respond_and_complete("继续完成旧任务。", outcome="completed"))
        return quiet, resumed

    quiet, resumed = asyncio.run(resume_old_list())
    assert quiet["success"] is True and quiet["status"] == "completed"
    assert resumed["success"] is False
    db_session.expire_all()
    assert all(item.status == "pending" for item in list_todo_items(db_session, work_state[1].id))

    async def runtime_rejects_false_success():
        update = await RequireToolCallMiddleware(completion_tool_name="respond_to_user").aafter_agent(
            {"messages": [ToolMessage(name="respond_to_user", content=json.dumps(failed), tool_call_id="end")]},
            None,
        )
        return update

    assert asyncio.run(runtime_rejects_false_success())["jump_to"] == "model"


def test_running_subagent_and_unconsumed_result_still_block(work_state):
    from services.agents.run_control import AgentRunControl
    from services.agents.tools.respond_to_user_tool import _respond_and_complete
    _, _, _, _, chapter = work_state

    async def scenario():
        control = AgentRunControl()
        gate = asyncio.Event()

        async def reviewing(child):
            await gate.wait()
            return {"success": True}

        supervisor.get_context()["run_control"] = control
        child = control.start("reviewer", chapter.id, reviewing)
        running = json.loads(await _respond_and_complete("写完了。", outcome="completed"))
        gate.set()
        await child.handle
        leftover = json.loads(await _respond_and_complete("写完了。", outcome="completed"))
        await control.close()
        return running, leftover

    running, leftover = asyncio.run(scenario())
    assert running["success"] is False and running["status"] == "running"
    assert leftover["success"] is False and leftover["status"] == "running"


def test_character_decision_is_saved_directly_without_reasoning_artifact(work_state, db_session, monkeypatch):
    work, session, _, _, chapter = work_state
    before = artifact_count(db_session, work.id)
    prose = "陆沉选择隔离观察，让同伴留在门外。"

    def write_decision(messages):
        last = messages[-1]
        call_id = last.get("tool_call_id")
        if last["role"] != "tool":
            return "read_node_content", "read", {"node_ids": [chapter.id]}
        if call_id == "read":
            digest = json.loads(last["content"])["nodes"][0]["content_sha256"]
            return "update_node", "edit", {
                "node_id": chapter.id, "mode": "overwrite", "content": prose,
                "expected_content_sha256": digest, "reason": "落实隔离观察",
            }
        return "respond_to_user", "finish", {"message": "第一章已改为隔离观察。", "outcome": "completed"}

    install_models(monkeypatch, [ScriptedModel(write_decision)])
    asyncio.run(SupervisorAgent().run("重写第一章，陆沉选择隔离观察。", context={
        "work_id": work.id, "session_id": session.id, "user_id": session.user_id,
    }))
    db_session.expire_all()
    db_session.refresh(chapter)
    assert chapter.content == prose
    assert artifact_count(db_session, work.id) == before
    assert db_session.query(WorkflowArtifact).filter_by(work_id=work.id, artifact_type="scene_reasoning").count() == 0


def test_todo_events_do_not_create_analysis_records(work_state, db_session):
    from services.agents.tools.todo_tools import _update_todolist_async, _write_todolist_async
    work, session, *_ = work_state
    before = artifact_count(db_session, work.id)
    asyncio.run(_write_todolist_async(["保存视角笔记"]))
    asyncio.run(_update_todolist_async("complete", task_id="T1"))
    db_session.expire_all()
    assert artifact_count(db_session, work.id) == before
    assert list_todo_items(db_session, session.id)[0].status == "completed"
