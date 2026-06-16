"""复现并验证 chapter 写入 Bug 的修复。

原始 Bug: `_generate_chapter_content_sync` 创建 Chapter 时未显式赋值
`chapter_number`，回落到 model 默认值 0，与既有记录冲突触发
`uq_work_chapter` 唯一约束。修复方案: 删除 chapter_number 列与唯一约束，
改由 (work_id, node_id) 隐式唯一（node_id 即业务键）。
"""
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import database as db_module
from app.database import Base
from app.main import app
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.chapter import Chapter


def _session():
    return db_module.SessionLocal()


def _seed_work():
    """创建 user + work；返回 work_id"""
    db = _session()
    try:
        email = f"u{uuid.uuid4().hex[:8]}@example.com"
        user = User(username="tester", email=email, password_hash="x")
        db.add(user)
        db.flush()
        work = CanvasWork(id=str(uuid.uuid4()), user_id=user.id, title="t")
        db.add(work)
        db.commit()
        return work.id
    finally:
        db.close()


def _seed_chapter_node_under(work_id):
    """在指定 work 下创建 chapter 节点；返回 chapter_node_id"""
    db = _session()
    try:
        node = Node(
            id=str(uuid.uuid4()),
            work_id=work_id,
            type="chapter",
            title="第1章：测试",
            content="",
        )
        db.add(node)
        db.commit()
        return node.id
    finally:
        db.close()


def _seed_chapter_node():
    """独立 work + chapter 节点；返回 chapter_node_id"""
    work_id = _seed_work()
    return _seed_chapter_node_under(work_id)


def test_chapters_table_has_no_chapter_number_column():
    """chapters 表不应再存在 chapter_number 列。"""
    insp = inspect(db_module.engine)
    cols = [c["name"] for c in insp.get_columns("chapters")]
    assert "chapter_number" not in cols


def test_chapters_table_has_no_uq_work_chapter_constraint():
    """uq_work_chapter 唯一约束不应再存在。"""
    insp = inspect(db_module.engine)
    uniques = insp.get_unique_constraints("chapters")
    names = [u.get("name") for u in uniques]
    assert "uq_work_chapter" not in names


def test_chapters_node_id_foreign_key_exists():
    """chapters.node_id -> nodes.id 外键约束必须存在。"""
    insp = inspect(db_module.engine)
    fks = insp.get_foreign_keys("chapters")
    node_fks = [
        fk for fk in fks if "node_id" in fk["constrained_columns"]
    ]
    assert len(node_fks) == 1
    assert node_fks[0]["referred_table"] == "nodes"
    assert "id" in node_fks[0]["referred_columns"]


def test_generate_chapter_content_is_idempotent(monkeypatch):
    """同一 chapter_node_id 重复调用 `_generate_chapter_content_sync`
    应是幂等更新，不应创建重复 Chapter 行。"""
    import sys
    ct_module = sys.modules["app.services.agents.tools.chapter_tools"]

    fake_result = {
        "content": "章节正文",
        "summary": "章节摘要",
        "new_facts": ["fact1"],
        "foreshadows": ["伏笔1"],
    }
    monkeypatch.setattr(
        ct_module, "generate_chapter", lambda ctx: fake_result
    )

    chapter_node_id = _seed_chapter_node()

    r1 = json.loads(
        ct_module._generate_chapter_content_sync(chapter_node_id)
    )
    assert r1.get("success") is True, f"第一次调用失败: {r1}"

    r2 = json.loads(
        ct_module._generate_chapter_content_sync(chapter_node_id)
    )
    assert r2.get("success") is True, f"第二次调用失败: {r2}"

    db = _session()
    try:
        count = (
            db.query(Chapter)
            .filter(Chapter.node_id == chapter_node_id)
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_generate_chapter_content_multi_chapter_in_same_work(monkeypatch):
    """复现 trace 里的真实 Bug: 同一 work 下两个不同 chapter_node_id
    分别生成内容时，因 chapter_number 默认 0 触发 uq_work_chapter 冲突。
    """
    import sys
    ct_module = sys.modules["app.services.agents.tools.chapter_tools"]

    fake_result = {
        "content": "正文",
        "summary": "摘要",
        "new_facts": [],
        "foreshadows": [],
    }
    monkeypatch.setattr(
        ct_module, "generate_chapter", lambda ctx: fake_result
    )

    work_id = _seed_work()
    node_id_1 = _seed_chapter_node_under(work_id)
    node_id_2 = _seed_chapter_node_under(work_id)

    r1 = json.loads(ct_module._generate_chapter_content_sync(node_id_1))
    assert r1.get("success") is True, f"第1章生成失败: {r1}"

    r2 = json.loads(ct_module._generate_chapter_content_sync(node_id_2))
    assert r2.get("success") is True, f"第2章生成失败(原 Bug): {r2}"


def test_generate_http_endpoint_persists_chapter(monkeypatch):
    """HTTP /api/generate 也必须正常写入 Chapter（不再因缺 work_id/
    chapter_number 触发冲突）。"""
    import app.services.chapter_generator as gen_module
    import app.routers.generate as router_module

    fake_result = {
        "content": "正文",
        "summary": "摘要",
        "new_facts": [],
        "foreshadows": [],
    }
    monkeypatch.setattr(
        gen_module, "generate_chapter", lambda ctx: fake_result
    )
    monkeypatch.setattr(
        router_module, "generate_chapter", lambda ctx: fake_result
    )

    chapter_node_id = _seed_chapter_node()
    client = TestClient(app)
    resp = client.post("/api/generate", json={"node_id": chapter_node_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] == "正文"

    db = _session()
    try:
        chapter = (
            db.query(Chapter)
            .filter(Chapter.node_id == chapter_node_id)
            .first()
        )
        assert chapter is not None
        assert chapter.work_id is not None
        assert chapter.summary == "摘要"
    finally:
        db.close()
