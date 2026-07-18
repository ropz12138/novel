"""数据库迁移 — 创建 character_relations 表（幂等）。"""
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
            WHERE table_name = 'character_relations'
            """,
        )
        if has_table:
            print("表 character_relations 已存在，跳过")
            engine.dispose()
            return

        print("创建 character_relations 表 ...")
        conn.execute(text("""
            CREATE TABLE character_relations (
                id VARCHAR(36) PRIMARY KEY,
                work_id VARCHAR(36) NOT NULL REFERENCES canvas_works(id) ON DELETE CASCADE,
                source_id VARCHAR(36) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                target_id VARCHAR(36) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                relation_type VARCHAR(100) NOT NULL,
                label VARCHAR(100) NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT ck_character_relation_no_self_loop CHECK (source_id <> target_id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_char_rel_work ON character_relations(work_id)"
        ))
        conn.execute(text(
            "CREATE INDEX idx_char_rel_source ON character_relations(source_id)"
        ))
        conn.execute(text(
            "CREATE INDEX idx_char_rel_target ON character_relations(target_id)"
        ))

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
