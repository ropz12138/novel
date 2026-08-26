import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.session_store import session_store

ctx_tools = importlib.import_module("services.agents.tools.context_tools")
query_tools = importlib.import_module("services.agents.tools.query_tools")
supervisor_mod = importlib.import_module("services.agents.supervisor")


def _make_user_work_session(db):
    user = User(username="ctx", email="ctx@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="ctx-work")
    db.add(work)
    db.commit()
    session = session_store.create_session(user.id, work.id)
    return user, work, session


def test_create_compaction_and_resolve_node_source():
    db = database.SessionLocal()
    try:
        _, work, session = _make_user_work_session(db)
        node = Node(work_id=work.id, type="chapter", title="第二章", content="男主在仓库醒来，暗金瞳一闪。")
        db.add(node)
        db.commit()
        supervisor_mod.set_context({"session_id": session["id"], "work_id": work.id})

        result = json.loads(ctx_tools._create_context_compaction_sync(
            summary="剧情连续性：[C1] 第二章结尾男主在仓库醒来，并出现暗金瞳。",
            citations=[{"citation_id": "C1", "source_type": "node", "node_id": node.id}],
            reason="历史过长",
        ))

        assert result["success"] is True
        pack_id = result["context_pack_id"]

        resolved = json.loads(ctx_tools._resolve_context_source_sync(
            context_pack_id=pack_id,
            citation_id="C1",
            mode="excerpt",
            query="暗金瞳",
        ))
        assert resolved["success"] is True
        assert resolved["source"]["node_id"] == node.id
        assert "暗金瞳" in resolved["content"]
    finally:
        supervisor_mod.set_context({})
        db.close()


def test_compaction_replaces_history_before_marker():
    db = database.SessionLocal()
    try:
        _, work, session = _make_user_work_session(db)
        old_user = session_store.add_message(session["id"], "user", "很早以前的长上下文", work_id=work.id)
        session_store.add_message(session["id"], "assistant", "旧回复", work_id=work.id)
        supervisor_mod.set_context({"session_id": session["id"], "work_id": work.id})

        result = json.loads(ctx_tools._create_context_compaction_sync(
            summary="压缩后的事实：[C1] 用户曾提供早期长上下文。",
            citations=[{"citation_id": "C1", "source_type": "message", "message_ids": [old_user["id"]]}],
            reason="历史过长",
        ))
        assert result["success"] is True

        session_store.add_message(session["id"], "tool_result", "{}", meta={"tool_name": "create_context_compaction"}, work_id=work.id)
        session_store.add_message(session["id"], "assistant", "压缩之后的新回复", work_id=work.id)

        history, _ = supervisor_mod.SupervisorAgent()._load_chat_history(session["id"])

        assert isinstance(history[0], SystemMessage)
        assert "压缩后的事实" in history[0].content
        assert all("很早以前的长上下文" not in getattr(m, "content", "") for m in history)
        assert any(isinstance(m, AIMessage) and m.content == "压缩之后的新回复" for m in history)
    finally:
        supervisor_mod.set_context({})
        db.close()


def test_read_node_content_blocks_compacted_node_by_default():
    db = database.SessionLocal()
    try:
        _, work, session = _make_user_work_session(db)
        node = Node(work_id=work.id, type="chapter", title="第一章", content="很长的原文")
        db.add(node)
        db.commit()
        supervisor_mod.set_context({"session_id": session["id"], "work_id": work.id})
        json.loads(ctx_tools._create_context_compaction_sync(
            summary="第一章摘要：[C1] 第一章发生了关键事件。",
            citations=[{"citation_id": "C1", "source_type": "node", "node_id": node.id}],
            reason="历史过长",
        ))

        blocked = json.loads(query_tools._read_node_content_sync([node.id]))
        assert blocked["success"] is False
        assert blocked["blocked_node_ids"] == [node.id]

        forced = json.loads(query_tools._read_node_content_sync([node.id], force_original_context=True))
        assert forced["total"] == 1
        assert forced["nodes"][0]["content"] == "很长的原文"
    finally:
        supervisor_mod.set_context({})
        db.close()


def test_context_window_status_uses_config_and_latest_usage():
    db = database.SessionLocal()
    try:
        _, work, session = _make_user_work_session(db)
        session_store.add_message(
            session["id"],
            "assistant",
            "ok",
            meta={"usage_metadata": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
            work_id=work.id,
        )
        supervisor_mod.set_context({"session_id": session["id"], "work_id": work.id})

        result = json.loads(ctx_tools._get_context_window_status_sync(
            planned_chars=3000,
            reserved_output_tokens=1000,
            model_name="deepseek-v4-flash",
        ))

        assert result["success"] is True
        assert result["context_limit_tokens"] == 512000
        assert result["latest_usage"]["input_tokens"] == 100
        assert result["estimated_planned_tokens"] == 1000

        supervisor_mod.set_context({
            "session_id": session["id"],
            "work_id": work.id,
            "last_llm_usage": {"input_tokens": 200, "output_tokens": 5, "total_tokens": 205},
        })
        current = json.loads(ctx_tools._get_context_window_status_sync(
            planned_chars=0,
            reserved_output_tokens=1000,
            model_name="deepseek-v4-flash",
        ))
        assert current["latest_usage"]["input_tokens"] == 200
    finally:
        supervisor_mod.set_context({})
        db.close()
