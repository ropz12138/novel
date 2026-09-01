"""角色关系线 character_relations — TDD。

- 独立表，仅 character ↔ character
- relation_type 为自然语言（非枚举），最长 100 字符
- 同一对角色（含反向）只允许一条关系线
- 禁止自环
- 主角 scope=global 可参与角色关系
- 画布关联线 edges 禁止 character ↔ character
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
import database
from node_types import validate_edge_endpoints, validate_character_relation
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.character_relation import CharacterRelation

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="tester", email="t@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_work(db, user_id):
    work = CanvasWork(user_id=user_id, title="w")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


def _make_character(db, work_id, title, scope="minor"):
    node = Node(sort_order=0, work_id=work_id, type="character", title=title, scope=scope)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


# ---------- validate_character_relation 纯函数 ----------

def test_validate_character_relation_rejects_non_character_type():
    err = validate_character_relation("character", "chapter")
    assert err is not None
    assert "character" in err


def test_validate_character_relation_accepts_two_characters():
    assert validate_character_relation("character", "character") is None


def test_validate_relation_type_rejects_empty():
    from node_types import validate_relation_type
    import pytest
    with pytest.raises(ValueError):
        validate_relation_type("")
    with pytest.raises(ValueError):
        validate_relation_type("   ")


def test_validate_relation_type_accepts_natural_language():
    from node_types import validate_relation_type
    assert validate_relation_type("表面同事，实为监视者") == "表面同事，实为监视者"


def test_validate_edge_endpoints_rejects_character_to_character():
    assert validate_edge_endpoints("character", "character", "minor", "major") is not None
    assert "character_relations" in validate_edge_endpoints("character", "character", "minor", "major")


# ---------- HTTP API ----------

def test_create_character_relation(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "张三")
        b = _make_character(db, work.id, "李四")
        resp = client.post(
            f"/api/works/{work.id}/character-relations",
            json={
                "source_id": a.id,
                "target_id": b.id,
                "relation_type": "暗恋",
                "label": "读者尚不知情",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["relation_type"] == "暗恋"
        assert data["label"] == "读者尚不知情"
        assert data["source_id"] == a.id
        assert data["target_id"] == b.id
    finally:
        db.close()


def test_create_character_relation_allows_protagonist(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        hero = _make_character(db, work.id, "主角", scope="global")
        side = _make_character(db, work.id, "配角")
        resp = client.post(
            f"/api/works/{work.id}/character-relations",
            json={
                "source_id": hero.id,
                "target_id": side.id,
                "relation_type": "师徒",
            },
        )
        assert resp.status_code == 201
    finally:
        db.close()


def test_create_character_relation_rejects_self_loop(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "张三")
        resp = client.post(
            f"/api/works/{work.id}/character-relations",
            json={
                "source_id": a.id,
                "target_id": a.id,
                "relation_type": "自我分裂",
            },
        )
        assert resp.status_code == 400
    finally:
        db.close()


def test_create_character_relation_rejects_non_character_endpoint(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "张三")
        ch = Node(sort_order=0, work_id=work.id, type="chapter", title="第一章")
        db.add(ch)
        db.commit()
        resp = client.post(
            f"/api/works/{work.id}/character-relations",
            json={
                "source_id": a.id,
                "target_id": ch.id,
                "relation_type": "登场",
            },
        )
        assert resp.status_code == 400
    finally:
        db.close()


def test_create_character_relation_rejects_second_same_direction(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "A")
        b = _make_character(db, work.id, "B")
        first = client.post(
            f"/api/works/{work.id}/character-relations",
            json={"source_id": a.id, "target_id": b.id, "relation_type": "同事"},
        )
        assert first.status_code == 201

        second = client.post(
            f"/api/works/{work.id}/character-relations",
            json={"source_id": a.id, "target_id": b.id, "relation_type": "暗中敌对"},
        )
        assert second.status_code == 409
        assert "A" in second.json()["detail"] or "同事" in second.json()["detail"]
        assert client.get(f"/api/works/{work.id}/character-relations").json()["total"] == 1
    finally:
        db.close()


def test_create_character_relation_rejects_reverse_pair(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "刘猛")
        b = _make_character(db, work.id, "林小鹿")
        first = client.post(
            f"/api/works/{work.id}/character-relations",
            json={"source_id": a.id, "target_id": b.id, "relation_type": "暗恋"},
        )
        assert first.status_code == 201

        second = client.post(
            f"/api/works/{work.id}/character-relations",
            json={"source_id": b.id, "target_id": a.id, "relation_type": "逐渐信赖"},
        )
        assert second.status_code == 409
        assert "林小鹿" in second.json()["detail"] or "刘猛" in second.json()["detail"]
        assert client.get(f"/api/works/{work.id}/character-relations").json()["total"] == 1
    finally:
        db.close()


def test_create_character_relation_tool_skips_existing_pair_with_warning(monkeypatch):
    import importlib
    rt = importlib.import_module("services.agents.tools.character_relation_tools")
    db = database.SessionLocal()
    try:
        user = User(username="x", email="x@x.x", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="w")
        db.add(work)
        db.commit()
        monkeypatch.setattr(rt, "_get_current_work_id", lambda: work.id)
        a = _make_character(db, work.id, "甲")
        b = _make_character(db, work.id, "乙")
        db.add(CharacterRelation(
            work_id=work.id,
            source_id=a.id,
            target_id=b.id,
            relation_type="师徒",
            label="",
        ))
        db.commit()

        result = json.loads(rt._create_character_relation_sync(b.id, a.id, "恋人"))
        assert result.get("skipped") is True
        assert "warning" in result
        assert result.get("success") is False
        assert db.query(CharacterRelation).filter(CharacterRelation.work_id == work.id).count() == 1
    finally:
        db.close()


def test_list_agent_update_delete_character_relation(mock_auth, monkeypatch):
    import importlib
    relation_tools = importlib.import_module(
        "services.agents.tools.character_relation_tools"
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        monkeypatch.setattr(relation_tools, "_get_current_work_id", lambda: work.id)
        a = _make_character(db, work.id, "A")
        b = _make_character(db, work.id, "B")
        created = client.post(
            f"/api/works/{work.id}/character-relations",
            json={"source_id": a.id, "target_id": b.id, "relation_type": "挚友"},
        ).json()
        rel_id = created["id"]

        updated = json.loads(
            relation_tools._update_character_relation_sync(
                rel_id,
                relation_type="生死之交",
                label="第三卷决裂前",
            )
        )
        assert updated["success"] is True
        listed = client.get(f"/api/works/{work.id}/character-relations").json()
        assert listed["relations"][0]["relation_type"] == "生死之交"
        assert listed["relations"][0]["label"] == "第三卷决裂前"

        deleted = client.delete(f"/api/character-relations/{rel_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/works/{work.id}/character-relations").json()["total"] == 0
    finally:
        db.close()


def test_restore_canvas_includes_character_relations(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_character(db, work.id, "A")
        b = _make_character(db, work.id, "B")
        rel_id = str(uuid.uuid4())

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [
                {
                    "id": a.id, "type": "character", "title": "A",
                    "scope": "minor", "layer": 0, "position_x": 0, "position_y": 0,
                },
                {
                    "id": b.id, "type": "character", "title": "B",
                    "scope": "minor", "layer": 0, "position_x": 100, "position_y": 0,
                },
            ],
            "edges": [],
            "character_relations": [{
                "id": rel_id,
                "source_id": a.id,
                "target_id": b.id,
                "relation_type": "恋人",
                "label": "",
            }],
        })
        assert resp.status_code == 200
        assert resp.json()["relation_count"] == 1
        db.expire_all()
        rel = db.query(CharacterRelation).filter(CharacterRelation.id == rel_id).first()
        assert rel is not None
        assert rel.relation_type == "恋人"
    finally:
        db.close()


def test_create_edge_rejects_character_pair(monkeypatch):
    import importlib
    nt = importlib.import_module("services.agents.tools.node_tools")
    db = database.SessionLocal()
    try:
        user = User(username="x", email="x@x.x", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="w")
        db.add(work)
        db.commit()
        monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
        a = _make_character(db, work.id, "A")
        b = _make_character(db, work.id, "B")
        r = json.loads(nt._create_edge_sync(a.id, b.id, edge_type="恋人"))
        assert "error" in r
    finally:
        db.close()
