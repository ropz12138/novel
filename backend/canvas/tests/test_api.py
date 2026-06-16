import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, engine, Base

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_health_check():
    response = client.post("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_node():
    response = client.post(
        "/api/nodes",
        json={
            "type": "idea",
            "title": "测试灵感",
            "content": "这是一个测试灵感",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "idea"
    assert data["title"] == "测试灵感"
    assert "id" in data


def test_list_nodes():
    client.post(
        "/api/nodes",
        json={"type": "idea", "title": "节点1"},
    )
    client.post(
        "/api/nodes",
        json={"type": "outline", "title": "节点2"},
    )

    response = client.get("/api/nodes")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["nodes"]) == 2


def test_get_node():
    create_response = client.post(
        "/api/nodes",
        json={"type": "idea", "title": "测试节点"},
    )
    node_id = create_response.json()["id"]

    response = client.get(f"/api/nodes/{node_id}")
    assert response.status_code == 200
    assert response.json()["id"] == node_id


def test_update_node():
    create_response = client.post(
        "/api/nodes",
        json={"type": "idea", "title": "原始标题"},
    )
    node_id = create_response.json()["id"]

    response = client.put(
        f"/api/nodes/{node_id}",
        json={"title": "更新后的标题"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "更新后的标题"


def test_delete_node():
    create_response = client.post(
        "/api/nodes",
        json={"type": "idea", "title": "要删除的节点"},
    )
    node_id = create_response.json()["id"]

    response = client.delete(f"/api/nodes/{node_id}")
    assert response.status_code == 204

    response = client.get(f"/api/nodes/{node_id}")
    assert response.status_code == 404


def test_create_edge():
    node1 = client.post(
        "/api/nodes",
        json={"type": "outline", "title": "大纲节点"},
    ).json()
    node2 = client.post(
        "/api/nodes",
        json={"type": "chapter", "title": "章节节点"},
    ).json()

    response = client.post(
        "/api/edges",
        json={
            "source_id": node1["id"],
            "target_id": node2["id"],
            "edge_type": "uses",
            "label": "使用关系",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_id"] == node1["id"]
    assert data["target_id"] == node2["id"]
    assert data["edge_type"] == "uses"


def test_list_edges():
    node1 = client.post(
        "/api/nodes",
        json={"type": "outline", "title": "节点1"},
    ).json()
    node2 = client.post(
        "/api/nodes",
        json={"type": "chapter", "title": "节点2"},
    ).json()

    client.post(
        "/api/edges",
        json={"source_id": node1["id"], "target_id": node2["id"], "edge_type": "uses"},
    )

    response = client.get("/api/edges")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1


def test_delete_edge():
    node1 = client.post(
        "/api/nodes",
        json={"type": "outline", "title": "节点1"},
    ).json()
    node2 = client.post(
        "/api/nodes",
        json={"type": "chapter", "title": "节点2"},
    ).json()

    edge = client.post(
        "/api/edges",
        json={"source_id": node1["id"], "target_id": node2["id"], "edge_type": "uses"},
    ).json()

    response = client.delete(f"/api/edges/{edge['id']}")
    assert response.status_code == 204

    response = client.get("/api/edges")
    assert response.json()["total"] == 0


def test_generate_requires_chapter_node():
    node = client.post(
        "/api/nodes",
        json={"type": "idea", "title": "非章节节点"},
    ).json()

    response = client.post(
        "/api/generate",
        json={"node_id": node["id"]},
    )
    assert response.status_code == 400
    assert "Only chapter nodes" in response.json()["detail"]


def test_generate_chapter():
    outline = client.post(
        "/api/nodes",
        json={
            "type": "outline",
            "title": "故事开头",
            "content": "主角在一个雨夜醒来，发现自己失去了记忆。",
        },
    ).json()

    chapter = client.post(
        "/api/nodes",
        json={
            "type": "chapter",
            "title": "第一章",
            "content": "",
        },
    ).json()

    client.post(
        "/api/edges",
        json={
            "source_id": outline["id"],
            "target_id": chapter["id"],
            "edge_type": "uses",
        },
    )

    response = client.post(
        "/api/generate",
        json={"node_id": chapter["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert "summary" in data
