"""数据库迁移脚本 - 为 nodes 表添加 layer 列，并将三纲类型合并为 outline。

背景:
    单 Agent 重构引入 layer 字段（整数）驱动前端垂直布局；
    同时 macro_outline/meso_outline/micro_outline 三纲类型合并为 outline。
    init_db 用 create_all 不会 ALTER 已有表，故需本脚本补列与数据兼容。
"""
import uuid

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
        # 1) nodes 表加 layer 列（INT NOT NULL DEFAULT 0）
        has_layer = _exists(
            conn,
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'nodes' AND column_name = 'layer'
            """,
        )
        if not has_layer:
            print("添加 nodes.layer 列 ...")
            conn.execute(
                text("ALTER TABLE nodes ADD COLUMN layer INTEGER NOT NULL DEFAULT 0")
            )
        else:
            print("列 nodes.layer 已存在，跳过")

        # 2) 三纲类型合并为 outline
        merged = conn.execute(
            text(
                "UPDATE nodes SET type = 'outline' "
                "WHERE type IN ('macro_outline', 'meso_outline', 'micro_outline')"
            )
        )
        if merged.rowcount:
            print(f"合并 {merged.rowcount} 条三纲节点为 outline")
        else:
            print("无三纲节点需合并")

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
