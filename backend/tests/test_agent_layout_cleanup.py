"""Agent 布局职责清理 — TDD

前端已按可见子图动态布局，Agent 写入的坐标不再被使用。Agent 不应再：
  - 被要求提供 position_x / position_y；
  - 收到 layout_warnings / layout_hint；
  - 进入"布局警告 → 移动节点 → 再次诊断"的循环。
"""
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

nt = importlib.import_module("services.agents.tools.node_tools")
qt = importlib.import_module("services.agents.tools.query_tools")


def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def _make_node(db, work_id, title="n", node_type="outline"):
    node = Node(work_id=work_id, type=node_type, title=title, layer=0)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


# ---------- 坐标成为可选 ----------

def test_create_node_input_coordinates_are_optional():
    fields = nt.CreateNodeInput.model_fields
    assert fields["position_x"].is_required() is False
    assert fields["position_y"].is_required() is False


def test_create_node_without_coordinates_succeeds(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync("outline", "大纲", content=""))
        assert result["success"] is True
    finally:
        db.close()


def test_batch_create_nodes_without_coordinates_succeeds(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {"node_type": "outline", "title": "大纲"},
            {"node_type": "volume", "title": "第一卷"},
        ]))
        assert result["success"] is True
        assert len(result["nodes"]) == 2
    finally:
        db.close()


# ---------- 不再返回布局反馈 ----------

def test_create_node_does_not_return_layout_feedback(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync("outline", "大纲"))
        assert "layout_warnings" not in result
        assert "layout_hint" not in result
    finally:
        db.close()


def test_update_node_does_not_return_layout_feedback(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = _make_node(db, work.id, "大纲")
        result = json.loads(nt._update_node_sync(node.id, title="新大纲"))
        assert "layout_warnings" not in result
        assert "layout_hint" not in result
    finally:
        db.close()


def test_create_edge_does_not_return_layout_feedback(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        outline = _make_node(db, work.id, "大纲", "outline")
        volume = _make_node(db, work.id, "第一卷", "volume")
        result = json.loads(nt._create_edge_sync(outline.id, volume.id, edge_type="包含"))
        assert "layout_warnings" not in result
        assert "layout_hint" not in result
    finally:
        db.close()


def test_batch_create_nodes_does_not_return_layout_feedback(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {"node_type": "outline", "title": "大纲"},
        ]))
        assert "layout_warnings" not in result
        assert "layout_hint" not in result
    finally:
        db.close()


# ---------- 布局诊断工具与模块移除 ----------

def test_layout_diagnostic_helpers_removed():
    for name in (
        "_collect_node_layout_warnings",
        "_collect_batch_layout_warnings",
        "_collect_edge_overlap_warnings",
        "_build_layout_hint",
    ):
        assert not hasattr(nt, name), f"{name} 应随布局职责一并移除"


def test_get_node_layout_issues_tool_removed():
    assert not hasattr(qt, "get_node_layout_issues")
    tool_names = {tool.name for tool in qt.query_tools}
    assert "get_node_layout_issues" not in tool_names


def test_node_layout_module_removed():
    try:
        importlib.import_module("services.agents.node_layout")
    except ModuleNotFoundError:
        return
    raise AssertionError("services.agents.node_layout 应被删除")


# ---------- 提示词不再要求 Agent 规划坐标 ----------

def test_layout_rules_text_states_frontend_owns_layout():
    from node_types import NODE_LAYOUT_RULES_TEXT

    assert "前端" in NODE_LAYOUT_RULES_TEXT
    assert "不会自动重排" not in NODE_LAYOUT_RULES_TEXT
    assert "画布左侧" not in NODE_LAYOUT_RULES_TEXT


def test_tool_descriptions_do_not_demand_coordinate_repair():
    for tool in (nt.create_node, nt.update_node, nt.batch_create_nodes):
        description = tool.description
        assert "layout_warnings" not in description
        assert "layout_hint" not in description
