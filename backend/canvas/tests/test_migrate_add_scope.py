"""migrate_add_scope 迁移脚本测试 — TDD。

验证：旧库（nodes 无 scope）跑迁移后补回 scope 列，并按类型回填：
worldbuilding/style → global，其余 → local。幂等。
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


def test_migrate_adds_scope_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        # 模拟旧库：删掉 scope 列
        with db_module.engine.connect() as conn:
            conn.execute(text("ALTER TABLE nodes DROP COLUMN scope"))
            conn.commit()

        import migrate_add_scope
        migrate_add_scope.migrate()

        with db_module.engine.connect() as conn:
            has = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='scope'"
                )
            ).scalar()
            assert has
            default = conn.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name='nodes' AND column_name='scope'"
                )
            ).scalar()
            assert "'local'" in (default or "")
    finally:
        db.close()


def test_migrate_backfills_scope_by_type(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        work = _make_work(db)
        # 各类型节点各一条
        for t in ("worldbuilding", "style", "character", "outline", "chapter"):
            db.add(Node(work_id=work.id, type=t, title=t, layer=0))
        db.commit()

        import migrate_add_scope
        migrate_add_scope.migrate()

        rows = {
            r[0]: r[1]
            for r in db.execute(
                text("SELECT type, scope FROM nodes WHERE work_id = :wid"),
                {"wid": work.id},
            ).fetchall()
        }
        assert rows["worldbuilding"] == "global"
        assert rows["style"] == "global"
        assert rows["character"] == "local"
        assert rows["outline"] == "local"
        assert rows["chapter"] == "local"
    finally:
        db.close()


def test_migrate_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    import migrate_add_scope
    migrate_add_scope.migrate()
    migrate_add_scope.migrate()
