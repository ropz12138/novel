"""manually_positioned 列测试 — TDD。

覆盖：
    _compact 返回 manually_positioned 字段
    _update_node_sync 支持设置 manually_positioned
    migrate_add_manually_positioned 迁移脚本
"""
import importlib
import json
from sqlalchemy import text
from app.config import settings
import app.database as db_module
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node

nt = importlib.import_module("app.services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: "test-work-id")
    user = User(username="mp", email="mp@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="mp-test")
    db.add(work)
    db.commit()
    return work


def test_compact_returns_manually_positioned(monkeypatch):
    db = db_module.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="idea", title="n1", layer=0)
        db.add(node)
        db.commit()
        compact = nt._compact(node)
        assert "manually_positioned" in compact
        assert compact["manually_positioned"] is False
    finally:
        db.close()


def test_update_node_sync_sets_manually_positioned(monkeypatch):
    db = db_module.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="outline", title="n1", layer=1)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id, manually_positioned=True, position_x=100, position_y=200
        ))
        assert result["success"] is True
        assert result["node"]["manually_positioned"] is True

        db.refresh(node)
        assert node.manually_positioned is True
        assert node.position_x == 100
        assert node.position_y == 200
    finally:
        db.close()


def test_update_node_sync_resets_manually_positioned(monkeypatch):
    db = db_module.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(work_id=work.id, type="chapter", title="n1", layer=2,
                    manually_positioned=True, position_x=50, position_y=60)
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id, manually_positioned=False, position_x=0, position_y=0
        ))
        assert result["success"] is True
        assert result["node"]["manually_positioned"] is False
    finally:
        db.close()


def test_migrate_adds_manually_positioned_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        with db_module.engine.connect() as conn:
            conn.execute(text("ALTER TABLE nodes DROP COLUMN manually_positioned"))
            conn.commit()

        import migrate_add_manually_positioned
        migrate_add_manually_positioned.migrate()

        with db_module.engine.connect() as conn:
            has = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='manually_positioned'"
                )
            ).scalar()
            assert has
            default = conn.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='manually_positioned'"
                )
            ).scalar()
            assert "false" in (default or "").lower()
    finally:
        db.close()


def test_migrate_manually_positioned_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    import migrate_add_manually_positioned
    migrate_add_manually_positioned.migrate()
    migrate_add_manually_positioned.migrate()
