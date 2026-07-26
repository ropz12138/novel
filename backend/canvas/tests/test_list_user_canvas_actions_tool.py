"""list_user_canvas_actions 工具 — TDD。"""
import importlib
import json

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.services import user_action_service as svc

qt = importlib.import_module("app.services.agents.tools.query_tools")


def _setup(monkeypatch, db):
    user = User(username="tool-test", email="tool@test.dev", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    db.refresh(work)
    monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)
    return work, user


def test_list_user_canvas_actions_returns_actions_newest_first(monkeypatch):
    db = database.SessionLocal()
    try:
        work, user = _setup(monkeypatch, db)
        from datetime import datetime, timedelta
        base = datetime(2025, 1, 1, 12, 0, 0)
        for i in range(3):
            n = Node(work_id=work.id, type="chapter", title=f"节点{i}", content="内容")
            db.add(n)
            db.commit()
            db.refresh(n)
            svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=n)
            from app.models.user_canvas_action import UserCanvasAction
            db.query(UserCanvasAction).filter(UserCanvasAction.target_title == f"节点{i}").first().created_at = base + timedelta(seconds=i)
        db.commit()

        result = json.loads(qt._list_user_canvas_actions_sync(limit=10))
        assert result["total"] == 3
        titles = [a["target_title"] for a in result["actions"]]
        assert titles == ["节点2", "节点1", "节点0"]
        assert "content_preview" in result["actions"][0]
    finally:
        db.close()


def test_list_user_canvas_actions_empty(monkeypatch):
    db = database.SessionLocal()
    try:
        _setup(monkeypatch, db)
        result = json.loads(qt._list_user_canvas_actions_sync(limit=10))
        assert result["actions"] == []
        assert "暂无" in result["message"]
    finally:
        db.close()


def test_list_user_canvas_actions_without_work_id(monkeypatch):
    db = database.SessionLocal()
    try:
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: None)
        result = json.loads(qt._list_user_canvas_actions_sync(limit=10))
        assert result["actions"] == []
        assert "暂无" in result["message"]
    finally:
        db.close()


def test_list_user_canvas_actions_registered_in_query_tools():
    names = [t.name for t in qt.query_tools]
    assert "list_user_canvas_actions" in names
