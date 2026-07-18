"""数据库迁移脚本 - 将 character 节点残留的 scope='local' 统一改为 'minor'。

背景:
    character 角色分类收紧为 global(主角)/major(主要配角)/minor(次要配角)/temp(临时)，
    废弃 local。历史 character 残留的 local 回填为 minor（次要配角，最接近原 local 语义）。
    非 character 的 local（层级链 outline/volume/plot/chapter）保持不变。
"""
from sqlalchemy import create_engine, text

from app.config import settings


def build_database_url() -> str:
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        updated = conn.execute(
            text(
                "UPDATE nodes SET scope = 'minor' "
                "WHERE type = 'character' AND scope = 'local'"
            )
        )
        if updated.rowcount:
            print(f"将 {updated.rowcount} 条 character 节点 scope 从 local 改为 minor")
        else:
            print("无 character 残留 local，跳过")
    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
