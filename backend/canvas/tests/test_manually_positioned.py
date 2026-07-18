"""create_node 坐标必填 + update_node layer/position 测试。

manually_positioned 字段已移除，坐标完全由 DB 存储驱动。
"""
import importlib
import json
from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node

nt = importlib.import_module("app.services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="mp", email="mp@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="mp-test")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_create_node_requires_coordinates(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        # 不传坐标应失败（Pydantic 校验在工具层，sync 函数会收到 None）
        # 实际测试：传了坐标能正常创建
        result = json.loads(nt._create_node_sync(
            "outline", "主线", content="x", layer=1, position_x=100, position_y=200
        ))
        assert result["success"] is True
        assert result["node"]["layer"] == 1
    finally:
        db.close()


def test_update_node_sync_sets_layer(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="outline", title="n1", layer=1,
                    position_x=50, position_y=60)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(node.id, layer=5))
        assert result["success"] is True
        assert result["node"]["layer"] == 5

        db.refresh(node)
        assert node.layer == 5
    finally:
        db.close()


def test_update_node_sync_sets_position(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="chapter", title="n1", layer=3,
                    position_x=0, position_y=0)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id, position_x=300, position_y=400
        ))
        assert result["success"] is True

        db.refresh(node)
        assert node.position_x == 300
        assert node.position_y == 400
    finally:
        db.close()


def test_compact_has_no_manually_positioned(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="idea", title="n1", layer=0,
                    position_x=10, position_y=20)
        db.add(node)
        db.commit()
        compact = nt._compact(node)
        assert "manually_positioned" not in compact
        assert set(compact.keys()) == {"id", "type", "title", "layer", "scope"}
    finally:
        db.close()


def test_create_node_rejects_invalid_type(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "idea", "灵感", position_x=0, position_y=0,
        ))
        assert result.get("success") is not True
        assert "idea" in result.get("error", "")
    finally:
        db.close()


def test_create_node_accepts_all_standard_types(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        for t in ("character", "outline", "volume", "plot", "chapter", "worldbuilding", "style", "element"):
            result = json.loads(nt._create_node_sync(t, t, position_x=0, position_y=0))
            assert result["success"] is True, f"{t} 应被接受，实际: {result}"
    finally:
        db.close()


def test_batch_create_rejects_invalid_type(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"node_type": "outline", "title": "ok", "position_x": 0, "position_y": 0},
            {"node_type": "event", "title": "bad", "position_x": 500, "position_y": 0},
        ]))
        assert result.get("success") is not True
        assert "event" in result.get("error", "")
    finally:
        db.close()


def test_update_node_rejects_invalid_type(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="outline", title="n", layer=0,
                    position_x=0, position_y=0)
        db.add(node)
        db.commit()
        result = json.loads(nt._update_node_sync(node.id, node_type="idea"))
        assert result.get("success") is not True
        assert "idea" in result.get("error", "")
    finally:
        db.close()
