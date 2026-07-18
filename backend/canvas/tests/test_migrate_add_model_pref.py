"""migrate_add_model_pref 迁移脚本测试 — TDD。

为 users 表添加 primary_model / fallback_model 两列（可为空）。
"""
from sqlalchemy import text

from app.config import settings
import app.database as db_module
from app.models.user import User


def test_migrate_adds_columns_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    db = db_module.SessionLocal()
    try:
        with db_module.engine.connect() as conn:
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS primary_model"))
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS fallback_model"))
            conn.commit()

        import migrate_add_model_pref
        migrate_add_model_pref.migrate()

        with db_module.engine.connect() as conn:
            for col in ("primary_model", "fallback_model"):
                has = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='users' AND column_name=:c"
                    ),
                    {"c": col},
                ).scalar()
                assert has
    finally:
        db.close()


def test_migrate_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "db_name", "novel_test")
    import migrate_add_model_pref
    migrate_add_model_pref.migrate()
    migrate_add_model_pref.migrate()
