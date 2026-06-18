"""数据库迁移脚本 - 删除 nodes.manually_positioned 列。"""
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
        has_col = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'nodes' AND column_name = 'manually_positioned'"
            )
        ).scalar()
        if has_col:
            print("删除 nodes.manually_positioned 列 ...")
            conn.execute(text("ALTER TABLE nodes DROP COLUMN manually_positioned"))
        else:
            print("列 nodes.manually_positioned 不存在，跳过")
    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
