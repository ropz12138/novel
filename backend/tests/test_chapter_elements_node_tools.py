"""create_node / update_node 不再接受 chapter_elements。"""
import importlib
import json

import pytest
from pydantic import ValidationError

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="chapter-elements", email="chapter-elements@test.dev", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="chapter-elements-work")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_create_element_node_is_rejected(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "element",
            "旧元素节点",
            position_x=0,
            position_y=0,
         sort_order=1,))
        assert "不支持的节点类型" in result["error"]
    finally:
        db.close()


def test_create_and_update_schemas_reject_chapter_elements():
    with pytest.raises(ValidationError):
        nt.CreateNodeInput(node_type="chapter", title="第一章", sort_order=1, chapter_elements=[{"title": "觉醒"}])
    with pytest.raises(ValidationError):
        nt.UpdateNodeInput(node_id="n1", chapter_elements=[{"title": "仓库醒来"}])
    assert "chapter_elements" not in str(nt.CreateNodeInput.model_json_schema())
    assert "chapter_elements" not in str(nt.UpdateNodeInput.model_json_schema())


def test_update_strips_existing_chapter_elements(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(sort_order=0,
            work_id=work.id,
            type="chapter",
            title="第一章",
            content="草稿",
            extra_data={"last_generation": {"ok": True}, "chapter_elements": [{"title": "仓库醒来"}]},
        )
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(node.id, title="第一章·改"))
        assert result["success"] is True
        db.refresh(node)
        assert node.title == "第一章·改"
        assert node.extra_data["last_generation"] == {"ok": True}
        assert "chapter_elements" not in (node.extra_data or {})
    finally:
        db.close()


def test_batch_create_rejects_chapter_elements(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {
                "sort_order": 1, "node_type": "chapter",
                "title": "第二章",
                "position_x": 0,
                "position_y": 0,
                "chapter_elements": [{"title": "暗金瞳", "content": "眼瞳异常被注意到"}],
            },
        ]))
        assert "error" in result
        assert "chapter_elements" in result["error"]
    finally:
        db.close()
