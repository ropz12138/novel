"""数据库迁移脚本 - 为 users 表添加 primary_model / fallback_model 列。

背景:
    引入用户级模型偏好（主/备模型），可空；空则回退 config.json 的 default_model/fallback_model。
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


COLUMNS = ("primary_model", "fallback_model")


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        for col in COLUMNS:
            has = _exists(
                conn,
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = :c
                """,
                c=col,
            )
            if not has:
                print(f"添加 users.{col} 列 ...")
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR(64) NULL"))
            else:
                print(f"列 users.{col} 已存在，跳过")

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
