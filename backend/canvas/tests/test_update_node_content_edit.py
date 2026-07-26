import asyncio
import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage

from app import database
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork

nt = importlib.import_module("app.services.agents.tools.node_tools")
llm_mod = importlib.import_module("app.services.agents.llm")
supervisor_mod = importlib.import_module("app.services.agents.supervisor")


class FakeLLM:
    def __init__(self, captured, response):
        self.captured = captured
        self.response = response

    async def astream(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        yield self.response


def _make_work(db):
    user = User(username="node-edit", email="node-edit@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="node-edit-work")
    db.add(work)
    db.commit()
    return work


def _edits_response(edits):
    return AIMessage(content=json.dumps({"edits": edits}, ensure_ascii=False))


def test_update_node_content_edit_applies_diff_and_emits(monkeypatch):
    captured = {}
    events = []

    async def collect(event, data):
        events.append((event, data))

    monkeypatch.setattr(
        llm_mod,
        "get_llm",
        lambda **kw: FakeLLM(captured, _edits_response([{
            "type": "replace",
            "paragraph_index": 2,
            "old_text": "旧对白",
            "new_text": "新对白",
        }])),
    )

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(
            work_id=work.id,
            type="chapter",
            title="第1章",
            content="第一段。\n\n他说：旧对白。",
        )
        db.add(node)
        db.commit()
        supervisor_mod.set_context({"work_id": work.id, "emit": collect})

        result = json.loads(asyncio.run(nt._update_node_async(
            node.id,
            content_edit_instruction="把第二段对白改掉",
            content_edit_context="角色说话更坚定",
        )))

        assert result["success"] is True
        assert result["content_edit"]["diff"]["hunks"][0]["new_text"] == "新对白"
        db.refresh(node)
        assert node.content == "第一段。\n\n他说：新对白。"

        human = captured["messages"][1]
        assert isinstance(human, HumanMessage)
        assert "把第二段对白改掉" in human.content
        assert "第一段。" in human.content
        assert "旧对白" in human.content
        assert "角色说话更坚定" in human.content

        event_names = [e for e, _ in events]
        assert "chapter_edit_diff" in event_names
        assert "nodes_updated" in event_names
    finally:
        supervisor_mod.set_context({})
        db.close()


def test_update_node_rejects_content_and_content_edit_together():
    result = json.loads(asyncio.run(nt._update_node_async(
        "node-id",
        content="整体覆盖",
        content_edit_instruction="局部修改",
    )))
    assert result["success"] is False
    assert "不能同时传" in result["error"]
