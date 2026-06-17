"""conftest.py — 让 pytest 能定位 `app` 包，并把被测代码的 DB 引擎
切换到独立的 `novel_test` 库，避免污染生产库。"""
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

CANVAS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CANVAS_DIR))

import pytest  # noqa: E402

from app import database as db_module  # noqa: E402
from app.database import Base  # noqa: E402

# 注册全部 canvas 模型到 Base.metadata，确保 relationship 能解析、create_all 建全表
import app.models.user  # noqa: E402, F401
import app.models.work  # noqa: E402, F401
import app.models.node  # noqa: E402, F401
import app.models.edge  # noqa: E402, F401
import app.models.chapter  # noqa: E402, F401
import app.models.session  # noqa: E402, F401


def _ensure_test_db(db_name: str = "novel_test") -> str:
    pg_url = (
        f"postgresql+psycopg2://{db_module.settings.db_user}:"
        f"{db_module.settings.db_password}@{db_module.settings.db_host}:"
        f"{db_module.settings.db_port}/postgres"
    )
    mgr = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with mgr.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"),
            {"n": db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    mgr.dispose()
    return (
        f"postgresql+psycopg2://{db_module.settings.db_user}:"
        f"{db_module.settings.db_password}@{db_module.settings.db_host}:"
        f"{db_module.settings.db_port}/{db_name}"
    )


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """每个测试用独立的 test 库；被测代码内部的 `_get_db()` 也会
    拿到指向 test 库的 SessionLocal。"""
    url = _ensure_test_db()
    test_engine = create_engine(url, pool_pre_ping=True)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # 彻底清空 schema，避免 main backend 残留表（共用 novel_test 库）
    # 导致 create_all 不重建表、drop_all 被外键阻塞。保证 TDD 干净基线。
    with test_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
