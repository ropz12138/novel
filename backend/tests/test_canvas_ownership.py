"""Canvas CRUD must authorize the owning work before reading or mutating it."""
import pytest
from fastapi.testclient import TestClient

from main import app
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user


@pytest.fixture
def canvas_owner(db_session):
    owner = User(username="owner", email="owner@canvas.test", password_hash="x")
    other = User(username="other", email="other@canvas.test", password_hash="x")
    db_session.add_all([owner, other])
    db_session.flush()
    work = CanvasWork(user_id=owner.id, title="private")
    db_session.add(work)
    db_session.flush()
    source = Node(work_id=work.id, type="chapter", title="note", sort_order=1)
    target = Node(work_id=work.id, type="chapter", title="note", sort_order=1)
    existing_target = Node(work_id=work.id, type="chapter", title="existing", sort_order=2)
    db_session.add_all([source, target, existing_target])
    db_session.flush()
    edge = Edge(work_id=work.id, source_id=source.id, target_id=existing_target.id, edge_type="contains")
    db_session.add(edge)
    db_session.commit()
    yield owner, other, work, source, target, edge
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("resource", ["nodes", "edges"])
@pytest.mark.parametrize("operation", ["create", "list", "update", "delete"])
@pytest.mark.parametrize("as_owner", [False, True])
def test_canvas_crud_requires_work_owner(db_session, canvas_owner, resource, operation, as_owner):
    owner, other, work, source, target, edge = canvas_owner
    app.dependency_overrides[get_current_user] = lambda: owner if as_owner else other
    client = TestClient(app)
    item = source if resource == "nodes" else edge
    collection = f"/api/works/{work.id}/{resource}"
    detail = f"/api/{resource}/{item.id}"
    if operation == "create":
        body = ({"type": "note", "title": "new", "sort_order": 2} if resource == "nodes" else
                {"source_id": source.id, "target_id": target.id, "edge_type": "contains"})
        response = client.post(collection, json=body)
        expected = 201 if resource == "nodes" else 400
    elif operation == "list":
        response = client.get(collection)
        expected = 200
    elif operation == "update":
        response = client.put(detail, json={"title": "changed"} if resource == "nodes" else {"label": "changed"})
        expected = 200
    else:
        response = client.delete(detail)
        expected = 204
    assert response.status_code == (expected if as_owner else 404), response.text
    if not as_owner:
        db_session.expire_all()
        assert db_session.query(Node).filter_by(work_id=work.id).count() == 3
        assert db_session.query(Edge).filter_by(work_id=work.id).count() == 1
        assert db_session.get(Node, source.id).title == "note"
        assert db_session.get(Edge, edge.id).label == ""


@pytest.mark.parametrize("resource", ["nodes", "edges"])
def test_missing_work_does_not_return_an_empty_collection(canvas_owner, resource):
    owner, *_ = canvas_owner
    app.dependency_overrides[get_current_user] = lambda: owner
    response = TestClient(app).get(f"/api/works/missing/{resource}")
    assert response.status_code == 404
