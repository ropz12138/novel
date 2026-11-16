"""角色之间的关系线已从后端移除。"""
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
import database
from node_types import validate_edge_endpoints
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node
from services.agents.supervisor import SupervisorAgent
from services.work_state import snapshot

client = TestClient(app)
SKILLS = Path(__file__).resolve().parents[1] / "services" / "agents"


def test_character_relation_routes_are_absent():
    missing = client.get("/api/works/work-1/character-relations")
    assert missing.status_code == 404
    created = client.post("/api/works/work-1/character-relations", json={
        "source_id": "a",
        "target_id": "b",
        "relation_type": "师徒",
    })
    assert created.status_code == 404


def test_supervisor_does_not_offer_character_relation_tools():
    names = {tool.name for tool in SupervisorAgent()._get_tools()}
    assert names.isdisjoint({
        "query_character_relations",
        "create_character_relation",
        "update_character_relation",
        "delete_character_relation",
    })


def test_work_snapshot_has_no_character_relations():
    db = database.SessionLocal()
    try:
        user = User(username="relation-gone", email="relation-gone@t.t", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="作品")
        db.add(work)
        db.commit()
        db.add(Node(sort_order=0, work_id=work.id, type="character", title="林雨", scope="minor"))
        db.commit()
        state = snapshot(work.id)
    finally:
        db.close()
    assert "character_relations" not in state
    assert state["nodes"][0]["title"] == "林雨"


def test_canvas_restore_ignores_character_relations():
    db = database.SessionLocal()
    try:
        user = User(username="restore-user", email="restore-user@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        work = CanvasWork(user_id=user.id, title="作品")
        db.add(work)
        db.commit()
        character = Node(sort_order=0, work_id=work.id, type="character", title="旧名", scope="minor")
        db.add(character)
        db.commit()
        response = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [{
                "id": character.id,
                "type": "character",
                "title": "新名",
                "scope": "minor",
                "layer": 0,
                "position_x": 0,
                "position_y": 0,
            }],
            "edges": [],
            "character_relations": [{
                "id": "rel-1",
                "source_id": character.id,
                "target_id": character.id,
                "relation_type": "师徒",
            }],
        })
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["node_count"] == 1
        assert "relation_count" not in body
        db.expire_all()
        assert db.get(Node, character.id).title == "新名"
        with database.engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('public.character_relations')")).scalar() is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.close()


def test_character_skills_do_not_instruct_relation_lines():
    texts = [
        (SKILLS / "skills" / "design-characters" / "SKILL.md").read_text(),
        (SKILLS / "skills" / "references" / "character_design.txt").read_text(),
        (SKILLS / "skills" / "maintain-story-memory" / "SKILL.md").read_text(),
        (SKILLS / "prompts" / "supervisor_system.txt").read_text(),
    ]
    for text_content in texts:
        assert "create_character_relation" not in text_content
        assert "角色关系工具" not in text_content
        assert "角色关系线" not in text_content


def test_edges_still_reject_character_endpoints():
    assert "角色不是画布连线端点" in validate_edge_endpoints("character", "character", "minor", "major")


def test_startup_drops_leftover_character_relation_storage():
    with database.engine.begin() as conn:
        conn.execute(text("CREATE TABLE character_relations (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE canvas_checkpoint_relations (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(text(
            "ALTER TABLE canvas_checkpoints ADD COLUMN relation_count INTEGER NOT NULL DEFAULT 0"
        ))
    database._drop_character_relation_storage()
    with database.engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.character_relations')")).scalar() is None
        assert conn.execute(text("SELECT to_regclass('public.canvas_checkpoint_relations')")).scalar() is None
        column = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'canvas_checkpoints' "
            "AND column_name = 'relation_count'"
        )).scalar()
        assert column is None
