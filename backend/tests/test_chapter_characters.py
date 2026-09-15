"""章节角色元素 extra_data.characters — TDD。

角色仍是完整 character 节点，但不靠画布连线表达登场。
章节只存角色名 + 角色节点 id（前端不展示 id）。
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node

nt = importlib.import_module("services.agents.tools.node_tools")
client = TestClient(app)


def _make_work(monkeypatch, db, title="章节角色元素"):
    user = User(username=f"ch-char-{title[:8]}", email=f"ch-char-{title[:8]}@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def _make_character(db, work_id, title="林川"):
    node = Node(work_id=work_id, type="character", title=title, sort_order=1, scope="minor")
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_create_chapter_accepts_characters(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "写入")
        character = _make_character(db, work.id, "林川")
        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            characters=[{"id": character.id, "name": "林川"}],
            sort_order=1,
        ))
        assert result["success"] is True, result
        node = db.query(Node).filter(Node.work_id == work.id, Node.type == "chapter").first()
        assert node.extra_data["characters"] == [{"id": character.id, "name": "林川"}]
        assert result.get("relation_warnings", []) == []
    finally:
        db.close()


def test_create_non_chapter_rejects_characters(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "非章节")
        character = _make_character(db, work.id)
        result = json.loads(nt._create_node_sync(
            "plot",
            "情节",
            characters=[{"id": character.id, "name": "林川"}],
            sort_order=1,
        ))
        assert result["error"] == "characters 只能用于 chapter 节点"
    finally:
        db.close()


def test_create_chapter_rejects_unknown_character_id(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db, "未知id")
        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            characters=[{"id": "missing-id", "name": "林川"}],
            sort_order=1,
        ))
        assert "error" in result
        assert "missing-id" in result["error"]
    finally:
        db.close()


def test_create_chapter_rejects_character_item_without_name(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "无名")
        character = _make_character(db, work.id)
        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            characters=[{"id": character.id}],
            sort_order=1,
        ))
        assert "error" in result
        assert "name" in result["error"]
    finally:
        db.close()


def test_create_chapter_rejects_duplicate_character_id(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "重复")
        character = _make_character(db, work.id)
        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            characters=[
                {"id": character.id, "name": "林川"},
                {"id": character.id, "name": "林川"},
            ],
            sort_order=1,
        ))
        assert "error" in result
        assert "重复" in result["error"]
    finally:
        db.close()


def test_update_chapter_characters_preserves_other_extra_data(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "合并")
        character = _make_character(db, work.id, "沈夜")
        node = Node(
            work_id=work.id,
            type="chapter",
            title="第一章",
            sort_order=1,
            extra_data={"last_generation": {"ok": True}, "chapter_elements": [{"title": "觉醒"}]},
        )
        db.add(node)
        db.commit()
        db.refresh(node)

        result = json.loads(nt._update_node_sync(
            node.id,
            characters=[{"id": character.id, "name": "沈夜"}],
        ))
        assert result["success"] is True, result
        db.refresh(node)
        assert node.extra_data["last_generation"] == {"ok": True}
        assert node.extra_data["chapter_elements"][0]["title"] == "觉醒"
        assert node.extra_data["characters"][0]["name"] == "沈夜"
    finally:
        db.close()


def test_create_chapter_without_characters_warns_to_use_characters_field(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "缺字段")
        _make_character(db, work.id, "沈夜")
        result = json.loads(nt._create_node_sync("chapter", "第三章", sort_order=1))
        assert result["success"] is True
        assert result["relation_warnings"]
        assert "characters" in result["relation_hint"]
        assert "create_edge" not in result["relation_hint"]
    finally:
        db.close()


@pytest.fixture
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="ch-char-api", email="ch-char-api@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def test_put_chapter_characters_via_rest(mock_auth):
    db = database.SessionLocal()
    try:
        work = CanvasWork(user_id=mock_auth.id, title="w")
        db.add(work)
        db.commit()
        character = _make_character(db, work.id, "温杏")
        chapter = Node(work_id=work.id, type="chapter", title="第一章", sort_order=1, extra_data={})
        db.add(chapter)
        db.commit()
        db.refresh(chapter)

        response = client.put(
            f"/api/nodes/{chapter.id}",
            json={"characters": [{"id": character.id, "name": "温杏"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["extra_data"]["characters"][0]["name"] == "温杏"
        assert response.json()["extra_data"]["characters"][0]["id"] == character.id
    finally:
        db.close()
