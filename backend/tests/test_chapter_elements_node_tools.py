import importlib
import json

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
        ))
        assert "不支持的节点类型" in result["error"]
    finally:
        db.close()


def test_create_chapter_accepts_chapter_elements(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            content="草稿",
            position_x=0,
            position_y=0,
            chapter_elements=[
                {"title": "主角觉醒", "content": "林远第一次感知时间异常", "priority": "high"},
            ],
        ))
        assert result["success"] is True
        node = db.query(Node).filter(Node.work_id == work.id, Node.type == "chapter").first()
        assert node.extra_data["chapter_elements"][0]["title"] == "主角觉醒"
        assert node.extra_data["chapter_elements"][0]["priority"] == "high"
    finally:
        db.close()


def test_create_non_chapter_rejects_chapter_elements(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "plot",
            "情节",
            position_x=0,
            position_y=0,
            chapter_elements=[{"title": "不该出现"}],
        ))
        assert result["error"] == "chapter_elements 只能用于 chapter 节点"
    finally:
        db.close()


def test_update_chapter_elements_preserves_other_extra_data(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(
            work_id=work.id,
            type="chapter",
            title="第一章",
            content="草稿",
            extra_data={"last_generation": {"ok": True}},
        )
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id,
            chapter_elements=[{"title": "仓库醒来", "content": "男主在仓库恢复意识"}],
        ))
        assert result["success"] is True
        db.refresh(node)
        assert node.extra_data["last_generation"] == {"ok": True}
        assert node.extra_data["chapter_elements"][0]["title"] == "仓库醒来"
    finally:
        db.close()


def test_batch_create_chapter_accepts_chapter_elements(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {
                "node_type": "chapter",
                "title": "第二章",
                "position_x": 0,
                "position_y": 0,
                "chapter_elements": [{"title": "暗金瞳", "content": "眼瞳异常被注意到"}],
            },
        ]))
        assert result["success"] is True
        node = db.query(Node).filter(Node.work_id == work.id, Node.title == "第二章").first()
        assert node.extra_data["chapter_elements"][0]["content"] == "眼瞳异常被注意到"
    finally:
        db.close()
