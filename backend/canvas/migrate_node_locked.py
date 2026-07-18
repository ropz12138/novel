"""数据库迁移脚本 - 为 nodes 表添加 locked 列。

背景:
    用户可手动固定节点，固定后 agent 无法调整该节点的坐标。
    init_db 用 create_all 不会 ALTER 已有表，故需本脚本补列。
"""
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
        has_locked = _exists(
            conn,
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'nodes' AND column_name = 'locked'
            """,
        )
        if not has_locked:
            print("添加 nodes.locked 列 ...")
            conn.execute(
                text("ALTER TABLE nodes ADD COLUMN locked BOOLEAN NOT NULL DEFAULT FALSE")
            )
        else:
            print("列 nodes.locked 已存在，跳过")
    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
