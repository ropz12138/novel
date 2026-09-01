"""节点同级顺序字段 sort_order — TDD。

同级顺序此前靠推断：extra_data 序号 → 标题「第N章」正则 → layer/position_x/created_at。
Agent 不再写坐标后 position_x 退化为常量，顺序实际落到 created_at 上，而批量创建
的时间戳可能相同，同级顺序因此不确定。改为创建时必须显式提供 sort_order。
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import database
from main import app
from models.node import Node
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user
from schemas.node import NodeCreate
from services.chapter_history_service import chapter_order_key, list_ordered_chapters

nt = importlib.import_module("services.agents.tools.node_tools")


# ---------- 模型与 schema ----------

def test_node_model_has_sort_order_column():
    column = Node.__table__.columns.get("sort_order")
    assert column is not None
    assert column.nullable is False


def test_node_create_requires_sort_order():
    with pytest.raises(ValidationError):
        NodeCreate(type="chapter", title="第一章")


def test_node_create_accepts_sort_order():
    payload = NodeCreate(type="chapter", title="第一章", sort_order=3)
    assert payload.sort_order == 3


def test_node_response_exposes_sort_order():
    from schemas.node import NodeResponse

    assert "sort_order" in NodeResponse.model_fields


def test_node_update_sort_order_is_optional():
    from schemas.node import NodeUpdate

    assert NodeUpdate().sort_order is None
    assert NodeUpdate(sort_order=5).sort_order == 5


# ---------- 排序 ----------

def _node(sort_order, node_id="n", title="章节"):
    return Node(id=node_id, work_id="w", type="chapter", title=title, sort_order=sort_order)


def test_chapter_order_key_uses_sort_order():
    assert chapter_order_key(_node(2))[0] == 2
    assert chapter_order_key(_node(10))[0] == 10


def test_chapter_order_key_ignores_title_and_extra_data():
    """顺序只认 sort_order：标题文字与 extra_data 不再参与推断。"""
    node = Node(
        id="n1",
        work_id="w",
        type="chapter",
        title="第 99 章",
        sort_order=1,
        extra_data={"chapter_number": 42},
    )
    assert chapter_order_key(node)[0] == 1


def test_chapter_order_key_is_deterministic_when_sort_order_ties():
    """并列时仍需确定顺序，否则排序结果在两次调用间可能不同。"""
    a = _node(1, node_id="a")
    b = _node(1, node_id="b")
    assert chapter_order_key(a) != chapter_order_key(b)
    assert sorted([b, a], key=chapter_order_key)[0].id == "a"


# ---------- HTTP API ----------

@pytest.fixture
def mock_auth():
    db = database.SessionLocal()
    db.add(User(id="u-sort", username="sort", email="sort@test.com", password_hash="x"))
    db.commit()
    db.close()

    app.dependency_overrides[get_current_user] = lambda: User(
        id="u-sort", username="sort", email="sort@test.com", password_hash="x"
    )
    yield
    app.dependency_overrides.clear()


def _make_work(work_id="w-sort"):
    db = database.SessionLocal()
    db.add(CanvasWork(id=work_id, user_id="u-sort", title="顺序作品"))
    db.commit()
    db.close()
    return work_id


def test_create_node_api_persists_sort_order(mock_auth):
    work_id = _make_work("w-sort-1")
    client = TestClient(app)
    resp = client.post(
        f"/api/works/{work_id}/nodes",
        json={"type": "chapter", "title": "第一章", "sort_order": 7},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["sort_order"] == 7


def test_create_node_api_rejects_missing_sort_order(mock_auth):
    work_id = _make_work("w-sort-2")
    client = TestClient(app)
    resp = client.post(
        f"/api/works/{work_id}/nodes",
        json={"type": "chapter", "title": "第一章"},
    )
    assert resp.status_code == 422


def test_list_ordered_chapters_sorts_by_sort_order(mock_auth):
    work_id = _make_work("w-sort-3")
    db = database.SessionLocal()
    for sort_order, title in [(3, "丙"), (1, "甲"), (2, "乙")]:
        db.add(
            Node(
                work_id=work_id,
                type="chapter",
                title=title,
                sort_order=sort_order,
                content="正文",
            )
        )
    db.commit()
    ordered = list_ordered_chapters(db, work_id)
    db.close()
    assert [n.title for n in ordered] == ["甲", "乙", "丙"]


# ---------- Agent 工具 ----------

@pytest.fixture
def tool_work(monkeypatch):
    """工具层从上下文取 work_id，不作为参数传入。"""
    db = database.SessionLocal()
    user = User(username="tool-sort", email="tool-sort@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="工具作品")
    db.add(work)
    db.commit()
    work_id = work.id
    db.close()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work_id)
    return work_id


def test_create_node_tool_schema_requires_sort_order():
    assert nt.CreateNodeInput.model_fields["sort_order"].is_required()


def test_update_node_tool_can_change_sort_order():
    assert "sort_order" in nt.UpdateNodeInput.model_fields
    assert nt.UpdateNodeInput.model_fields["sort_order"].is_required() is False


def test_create_node_tool_rejects_missing_sort_order(tool_work):
    result = json.loads(nt._create_node_sync("chapter", "第一章"))
    assert "error" in result
    assert "sort_order" in result["error"]


def test_batch_create_nodes_rejects_item_without_sort_order(tool_work):
    """每项是自由 dict，缺 sort_order 必须报错，不能默认成 0。"""
    result = json.loads(
        nt._batch_create_nodes_sync([{"node_type": "volume", "title": "第一卷"}])
    )
    assert "error" in result
    assert "sort_order" in result["error"]


def test_create_node_tool_persists_sort_order(tool_work):
    result = json.loads(nt._create_node_sync("chapter", "第一章", sort_order=4))
    assert result.get("success") is True, result
    db = database.SessionLocal()
    node = db.query(Node).filter(Node.id == result["node"]["id"]).first()
    sort_order = node.sort_order
    db.close()
    assert sort_order == 4


def test_batch_create_nodes_tool_persists_sort_order(tool_work):
    result = json.loads(
        nt._batch_create_nodes_sync([
            {"node_type": "volume", "title": "第一卷", "sort_order": 1},
            {"node_type": "volume", "title": "第二卷", "sort_order": 2},
        ])
    )
    assert result.get("success") is True, result
    db = database.SessionLocal()
    orders = {
        n.title: n.sort_order
        for n in db.query(Node).filter(Node.work_id == tool_work).all()
    }
    db.close()
    assert orders == {"第一卷": 1, "第二卷": 2}


def test_update_node_tool_changes_sort_order(tool_work):
    created = json.loads(nt._create_node_sync("chapter", "第一章", sort_order=1))
    node_id = created["node"]["id"]

    result = json.loads(nt._update_node_sync(node_id, sort_order=9))
    assert result.get("success") is True, result

    db = database.SessionLocal()
    sort_order = db.query(Node).filter(Node.id == node_id).first().sort_order
    db.close()
    assert sort_order == 9
