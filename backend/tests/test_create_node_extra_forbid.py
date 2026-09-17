"""create_node / batch_create_nodes 拒绝未知参数，尤其是 parent_node_id。"""
import json

import pytest
from pydantic import ValidationError

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from services.agents.supervisor import _structured_tool_error
from services.agents.tools import node_tools as nt


@pytest.fixture
def tool_work(monkeypatch):
    db = database.SessionLocal()
    user = User(username="create-extra-forbid", email="create-extra-forbid@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="工具作品")
    db.add(work)
    db.commit()
    work_id = work.id
    db.close()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work_id)
    return work_id


def test_create_node_schema_forbids_extra_fields():
    assert nt.CreateNodeInput.model_config.get("extra") == "forbid"


def test_create_node_input_accepts_legal_fields():
    payload = nt.CreateNodeInput(node_type="chapter", title="第一章", sort_order=1)
    assert payload.title == "第一章"


def test_create_node_input_rejects_parent_node_id():
    with pytest.raises(ValidationError) as exc_info:
        nt.CreateNodeInput(
            node_type="chapter",
            title="第二章：求生之路",
            sort_order=2,
            parent_node_id="b1c52cfe-6c9c-4e7b-9ec8-de87254c0ef7",
        )
    message = str(exc_info.value)
    assert "parent_node_id" in message
    assert "assemble_chapter_context" in message
    assert "create_edge" in message


def test_create_node_input_rejects_unknown_field():
    with pytest.raises(ValidationError) as exc_info:
        nt.CreateNodeInput(
            node_type="plot",
            title="情节",
            sort_order=1,
            unknown_field="x",
        )
    assert "unknown_field" in str(exc_info.value)


def test_parent_node_id_validation_error_is_structured_for_model_correction():
    try:
        nt.CreateNodeInput(
            node_type="chapter",
            title="第二章",
            sort_order=2,
            parent_node_id="plot-id",
        )
    except ValidationError as exc:
        result = json.loads(_structured_tool_error(exc))
    else:
        raise AssertionError("parent_node_id 应触发 ValidationError")

    assert result["success"] is False
    assert result["error"]["code"] == "tool_argument_validation_failed"
    joined = json.dumps(result, ensure_ascii=False)
    assert "assemble_chapter_context" in joined
    assert "create_edge" in joined


def test_create_node_description_rejects_parent_node_id():
    assert "不接受 parent_node_id" in nt.create_node.description
    assert "assemble_chapter_context" in nt.create_node.description
    assert "create_edge" in nt.create_node.description


def test_batch_create_nodes_rejects_parent_node_id(tool_work):
    result = json.loads(nt._batch_create_nodes_sync([
        {
            "node_type": "chapter",
            "title": "第二章：求生之路",
            "sort_order": 2,
            "parent_node_id": "b1c52cfe-6c9c-4e7b-9ec8-de87254c0ef7",
        },
    ]))
    assert "error" in result
    assert "assemble_chapter_context" in result["error"]
    assert "create_edge" in result["error"]
    db = database.SessionLocal()
    try:
        count = db.query(Node).filter(Node.work_id == tool_work, Node.title == "第二章：求生之路").count()
        assert count == 0
    finally:
        db.close()
