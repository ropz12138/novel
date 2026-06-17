"""migrate_add_layer 迁移脚本测试 — TDD。

验证：旧库（nodes 无 layer）跑迁移后补回 layer 列；三纲类型合并为 outline。
通过 monkeypatch settings.db_name 让脚本连 test 库。
"""
from sqlalchemy import text

from app.config import settings
import app.database as db_module
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_migrate_adds_layer_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        # 模拟旧库：删掉 layer 列
        with db_module.engine.connect() as conn:
            conn.execute(text("ALTER TABLE nodes DROP COLUMN layer"))
            conn.commit()

        import migrate_add_layer
        migrate_add_layer.migrate()

        with db_module.engine.connect() as conn:
            has = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='layer'"
                )
            ).scalar()
            assert has
            default = conn.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='layer'"
                )
            ).scalar()
            assert "0" in (default or "")
    finally:
        db.close()


def test_migrate_merges_three_outline_types(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        work = _make_work(db)
        for t in ("macro_outline", "meso_outline", "micro_outline"):
            db.add(Node(work_id=work.id, type=t, title=t, layer=0))
        db.commit()

        import migrate_add_layer
        migrate_add_layer.migrate()

        rows = db.execute(
            text("SELECT DISTINCT type FROM nodes WHERE work_id = :wid"),
            {"wid": work.id},
        ).fetchall()
        types = {r[0] for r in rows}
        assert types == {"outline"}
    finally:
        db.close()


def test_migrate_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    import migrate_add_layer
    migrate_add_layer.migrate()
    migrate_add_layer.migrate()
