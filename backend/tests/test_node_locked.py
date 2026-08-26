"""节点锁定（locked）功能测试。

需求：
- 用户可通过 API 设置节点 locked=true
- locked 节点的 position_x/position_y 不能被 agent 工具修改
- agent 尝试移动锁定节点时，工具返回自然语言提示
- locked 节点的其他属性（title/content/layer/scope）仍可被 agent 正常修改
"""
import asyncio
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="lk", email="lk@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="lk-test")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_update_node_sync_sets_locked(monkeypatch):
    """agent 工具应能设置 locked 字段（供后续通过 API 触发，此处直接验证 sync 函数）。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="outline", title="n1", layer=0,
                    position_x=10, position_y=20, locked=False)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(node.id, locked=True))
        assert result["success"] is True
        db.refresh(node)
        assert node.locked is True
    finally:
        db.close()


def test_update_node_sync_blocks_position_when_locked(monkeypatch):
    """锁定节点的 position_x/position_y 不可被 agent 修改。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="chapter", title="locked", layer=3,
                    position_x=100, position_y=200, locked=True)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id, position_x=999, position_y=888
        ))
        # 坐标被拦截：不应成功修改坐标
        assert result.get("success") is not True
        assert "锁定" in json.dumps(result, ensure_ascii=False)
        # 坐标保持原值
        db.refresh(node)
        assert node.position_x == 100
        assert node.position_y == 200
    finally:
        db.close()


def test_update_node_sync_position_when_only_x_and_locked(monkeypatch):
    """只改 position_x 时，锁定节点也应被拦截。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="chapter", title="lx", layer=3,
                    position_x=50, position_y=60, locked=True)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(node.id, position_x=500))
        assert result.get("success") is not True
        db.refresh(node)
        assert node.position_x == 50
    finally:
        db.close()


def test_update_node_sync_allows_other_fields_when_locked(monkeypatch):
    """锁定节点的 title/content/layer 等仍可被 agent 修改。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="outline", title="orig", layer=1,
                    position_x=10, position_y=20, content="old", locked=True)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id, title="new", content="new body", layer=5
        ))
        assert result["success"] is True
        db.refresh(node)
        assert node.title == "new"
        assert node.content == "new body"
        assert node.layer == 5
        # 坐标保持不变
        assert node.position_x == 10
        assert node.position_y == 20
    finally:
        db.close()


def test_update_node_sync_unblocked_when_not_locked(monkeypatch):
    """未锁定节点坐标修改正常。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="chapter", title="free", layer=3,
                    position_x=0, position_y=0, locked=False)
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


def test_compact_includes_locked(monkeypatch):
    """_compact 返回应包含 locked 字段，便于前端与 agent 感知状态。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="idea", title="n1", layer=0,
                    position_x=10, position_y=20, locked=True)
        db.add(node)
        db.commit()
        compact = nt._compact(node)
        assert compact["locked"] is True
    finally:
        db.close()


def test_update_node_async_accepts_locked_kwarg(monkeypatch):
    """StructuredTool 会按 schema 传入 locked=None，async 包装不得崩溃。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="character", title="角色", layer=2,
                    position_x=10, position_y=20, content="旧设定", locked=False)
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            nt._update_node_async(node.id, content="新设定", locked=None, reason="测试")
        ))
        assert result["success"] is True
        db.refresh(node)
        assert node.content == "新设定"
    finally:
        db.close()
