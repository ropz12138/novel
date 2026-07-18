"""数据库迁移 — 创建 chapter_illustrations 表（幂等）。"""
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
            WHERE table_name = 'chapter_illustrations'
            """,
        )
        if has_table:
            print("表 chapter_illustrations 已存在，跳过")
            engine.dispose()
            return

        print("创建 chapter_illustrations 表 ...")
        conn.execute(text("""
            CREATE TABLE chapter_illustrations (
                id VARCHAR(36) PRIMARY KEY,
                work_id VARCHAR(36) NOT NULL REFERENCES canvas_works(id) ON DELETE CASCADE,
                node_id VARCHAR(36) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                prompt TEXT NOT NULL,
                insert_after_paragraph INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_chapter_illustrations_work ON chapter_illustrations(work_id)"
        ))
        conn.execute(text(
            "CREATE INDEX idx_chapter_illustrations_node ON chapter_illustrations(node_id)"
        ))

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
