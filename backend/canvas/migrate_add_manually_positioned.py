"""数据库迁移脚本 - 为 nodes 表添加 manually_positioned 列。

背景:
    前端手动拖拽节点后需持久化标记，避免 autoLayout 覆盖。
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
        has_col = _exists(
            conn,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'nodes' AND column_name = 'manually_positioned'",
        )
        if not has_col:
            print("添加 nodes.manually_positioned 列 ...")
            conn.execute(
                text(
                    "ALTER TABLE nodes ADD COLUMN manually_positioned "
                    "BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
        else:
            print("列 nodes.manually_positioned 已存在，跳过")
    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
