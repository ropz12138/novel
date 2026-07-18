"""数据库迁移 — 创建 todo_items 表（幂等）。"""
from sqlalchemy import create_engine, text

from app.config import settings


def build_database_url() -> str:
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def _exists(conn, sql, **params):
    return conn.execute(text(sql), params).scalar()


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        has_table = _exists(
            conn,
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'todo_items'
            """,
        )
        if has_table:
            print("表 todo_items 已存在，跳过")
            engine.dispose()
            return

        print("创建 todo_items 表 ...")
        conn.execute(text("""
            CREATE TABLE todo_items (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL REFERENCES supervisor_sessions(id) ON DELETE CASCADE,
                task_id VARCHAR(20) NOT NULL,
                task TEXT NOT NULL DEFAULT '',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_todo_items_session ON todo_items(session_id)"
        ))

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
