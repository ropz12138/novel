"""结构线 label 策略 — TDD

- create_edge / batch_create_edges：无 label 入参，创建时 label 恒为空
- update_edge：保留 label，用于补充深层关系说明
"""
import importlib
import inspect

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge

nt = importlib.import_module("app.services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def _make_node(db, work_id, title="n", x=0.0, y=0.0):
    node = Node(
        work_id=work_id,
        type="outline",
        title=title,
        layer=0,
        position_x=x,
        position_y=y,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_create_edge_input_has_no_label_field():
    assert "label" not in nt.CreateEdgeInput.model_fields


def test_update_edge_input_has_label_field():
    assert "label" in nt.UpdateEdgeInput.model_fields
    desc = nt.UpdateEdgeInput.model_fields["label"].description or ""
    assert "深层关系" in desc


def test_create_edge_sync_has_no_label_parameter():
    params = inspect.signature(nt._create_edge_sync).parameters
    assert "label" not in params


def test_create_edge_always_empty_label(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        a = _make_node(db, wid, "A", x=0, y=0)
        b = _make_node(db, wid, "B", x=400, y=0)

        result = __import__("json").loads(
            nt._create_edge_sync(a.id, b.id, edge_type="包含"),
        )

        assert result["success"] is True
        assert result["edge"]["label"] == ""
        edge = db.query(Edge).filter(Edge.id == result["edge"]["id"]).first()
        assert edge.label == ""
    finally:
        db.close()


def test_batch_create_edges_ignores_label_in_data(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        a = _make_node(db, wid, "A", x=0, y=0)
        b = _make_node(db, wid, "B", x=400, y=0)

        result = __import__("json").loads(nt._batch_create_edges_sync([
            {
                "source_id": a.id,
                "target_id": b.id,
                "edge_type": "包含",
                "label": "不应写入",
            },
        ]))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == a.id).first()
        assert edge.label == ""
    finally:
        db.close()


def test_update_edge_can_set_deep_relation_label(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        a = _make_node(db, wid, "A", x=0, y=0)
        b = _make_node(db, wid, "B", x=400, y=0)
        nt._create_edge_sync(a.id, b.id, edge_type="包含")
        edge = db.query(Edge).filter(Edge.source_id == a.id).first()
        assert edge.label == ""

        deep = "表面师徒，实为监视者"
        result = __import__("json").loads(nt._update_edge_sync(edge.id, label=deep))

        assert result["success"] is True
        db.refresh(edge)
        assert edge.label == deep
    finally:
        db.close()
