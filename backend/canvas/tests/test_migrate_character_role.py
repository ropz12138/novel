"""migrate_character_role 迁移脚本测试 — TDD。

将 character 节点中残留的 scope='local' 迁移为 'minor'（次要配角）。
character 不再允许 local；非 character 的 local（层级链）保持不变。
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


def test_migrate_character_local_to_minor(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        work = _make_work(db)
        # character 残留 local
        c_local = Node(work_id=work.id, type="character", title="旧配角", scope="local")
        # character 已分类的保持不变
        c_major = Node(work_id=work.id, type="character", title="主要", scope="major")
        c_global = Node(work_id=work.id, type="character", title="主角", scope="global")
        # 层级链 local 不受影响
        outline = Node(work_id=work.id, type="outline", title="主线", scope="local")
        db.add_all([c_local, c_major, c_global, outline])
        db.commit()

        import migrate_character_role
        migrate_character_role.migrate()

        rows = {
            r[0]: r[1]
            for r in db.execute(
                text("SELECT title, scope FROM nodes WHERE work_id = :wid"),
                {"wid": work.id},
            ).fetchall()
        }
        assert rows["旧配角"] == "minor"      # local → minor
        assert rows["主要"] == "major"        # 不变
        assert rows["主角"] == "global"       # 不变
        assert rows["主线"] == "local"        # 层级链 local 不变
    finally:
        db.close()


def test_migrate_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    import migrate_character_role
    migrate_character_role.migrate()
    migrate_character_role.migrate()
