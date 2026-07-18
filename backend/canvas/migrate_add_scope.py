"""数据库迁移脚本 - 为 nodes 表添加 scope 列并按类型回填。

背景:
    引入节点作用域 scope(global/local)：worldbuilding/style 固定为 global，
    其余类型默认 local。init_db 用 create_all 不会 ALTER 已有表，故需本脚本补列与回填。
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


# 固定为 global 的类型，回填时按此判定
GLOBAL_LOCKED_TYPES = ("worldbuilding", "style")


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        # 1) nodes 表加 scope 列（VARCHAR(20) NOT NULL DEFAULT 'local'）
        has_scope = _exists(
            conn,
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'nodes' AND column_name = 'scope'
            """,
        )
        if not has_scope:
            print("添加 nodes.scope 列 ...")
            conn.execute(
                text("ALTER TABLE nodes ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'local'")
            )
        else:
            print("列 nodes.scope 已存在，跳过")

        # 2) 按类型回填：worldbuilding/style → global
        updated = conn.execute(
            text(
                "UPDATE nodes SET scope = 'global' "
                "WHERE type IN ('worldbuilding', 'style')"
            )
        )
        if updated.rowcount:
            print(f"回填 {updated.rowcount} 条 worldbuilding/style 节点为 global")
        else:
            print("无 worldbuilding/style 节点需回填")

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
