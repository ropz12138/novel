"""删除结构节点后，章节独立排序，所有写入入口拒绝旧类型。"""
import json

import pytest
from sqlalchemy import inspect, text
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from models.node import Node
from models.user import User
from models.work import CanvasWork
from node_types import STANDARD_NODE_TYPES, validate_node_type
from routers.auth import get_current_user
from schemas.canvas_snapshot import SnapshotNode
from services.agents.tools import node_tools as nt
from services.chapter_catalog_service import build_chapter_catalog


@pytest.fixture
def work(db_session, monkeypatch):
    user = User(username="flat", email="flat@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="独立章节")
    db_session.add(work)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    yield work
    app.dependency_overrides.pop(get_current_user, None)


def test_only_five_node_types():
    assert STANDARD_NODE_TYPES == {"chapter", "character", "worldbuilding", "note", "reviewer_note"}


@pytest.mark.parametrize("removed", ["outline", "volume", "plot"])
def test_removed_types_rejected_at_write_boundaries(work, db_session, removed):
    with pytest.raises(ValueError):
        validate_node_type(removed)
    with pytest.raises(ValidationError):
        SnapshotNode(id="old", type=removed, title="旧节点")
    client = TestClient(app)
    assert client.post(f"/api/works/{work.id}/nodes", json={
        "type": removed, "title": "旧节点", "sort_order": 1,
    }).status_code == 400
    chapter = Node(work_id=work.id, type="chapter", title="正文", sort_order=1)
    db_session.add(chapter)
    db_session.commit()
    assert client.put(f"/api/nodes/{chapter.id}", json={"type": removed}).status_code == 400
    assert "error" in json.loads(nt._create_node_sync(removed, "旧节点", sort_order=1))
    assert "error" in json.loads(nt._update_node_sync(chapter.id, node_type=removed))
    assert "error" in json.loads(nt._batch_create_nodes_sync([
        {"node_type": removed, "title": "旧节点", "sort_order": 1},
    ]))
    db_session.expire_all()
    assert db_session.get(Node, chapter.id).type == "chapter"
    assert db_session.query(Node).filter(Node.type == removed).count() == 0


def test_catalog_includes_standalone_chapters_and_tracks_order(work, db_session):
    chapters = [Node(id=f"chapter-{i}", work_id=work.id, type="chapter", title=f"章{i}", sort_order=i)
                for i in (3, 1, 2)]
    db_session.add_all(chapters)
    db_session.commit()
    ordered, revision, issues = build_chapter_catalog(db_session, work.id)
    assert [n.sort_order for n in ordered] == [1, 2, 3]
    assert issues == []
    chapters[0].sort_order = 0
    db_session.commit()
    ordered, changed, issues = build_chapter_catalog(db_session, work.id)
    assert ordered[0].id == chapters[0].id
    assert changed != revision


def test_cleanup_preserves_chapter_order_content_and_checkpoint(work, db_session):
    from models.chapter import Chapter
    from models.edge import Edge
    from models.session import SupervisorSession, SupervisorMessage
    from models.canvas_checkpoint import CanvasCheckpoint, CanvasCheckpointNode, CanvasCheckpointEdge
    from models.user_canvas_action import UserCanvasAction
    from services.structure_node_cleanup import remove_structure_nodes

    rows = [
        Node(id="o", work_id=work.id, type="outline", title="纲", sort_order=1),
        Node(id="v1", work_id=work.id, type="volume", title="卷1", sort_order=1),
        Node(id="v2", work_id=work.id, type="volume", title="卷2", sort_order=2),
        Node(id="p1", work_id=work.id, type="plot", title="情节1", sort_order=1),
        Node(id="p2", work_id=work.id, type="plot", title="情节2", sort_order=1),
        Node(id="c1", work_id=work.id, type="chapter", title="章1", sort_order=2, content="正文1", extra_data={"characters": [{"id": "hero", "name": "角色"}]}),
        Node(id="c2", work_id=work.id, type="chapter", title="章2", sort_order=1, content="正文2"),
        Node(id="c3", work_id=work.id, type="chapter", title="独立章", sort_order=0, content="正文3"),
        Node(id="n", work_id=work.id, type="note", title="笔记", sort_order=1, scope="global", content="要求"),
        Node(id="hero", work_id=work.id, type="character", title="角色", sort_order=1, scope="major", content="角色设定"),
        Node(id="w", work_id=work.id, type="worldbuilding", title="世界观", sort_order=1, scope="global", content="世界规则"),
        Node(id="r", work_id=work.id, type="reviewer_note", title="评审笔记", sort_order=1, scope="global", content="评审标准"),
    ]
    db_session.add_all(rows)
    db_session.flush()
    for a, b in [("o", "v1"), ("o", "v2"), ("v1", "p1"), ("v2", "p2"), ("p1", "c1"), ("p2", "c2")]:
        db_session.add(Edge(work_id=work.id, source_id=a, target_id=b, edge_type="contains"))
    db_session.add(Chapter(work_id=work.id, node_id="c1", content="正文1", notes="章节笔记"))
    db_session.add(UserCanvasAction(work_id=work.id, user_id=work.user_id, action_type="node_create", target_id="o", target_type="outline"))
    session = SupervisorSession(work_id=work.id, user_id=work.user_id, title="会话")
    db_session.add(session)
    db_session.flush()
    message = SupervisorMessage(session_id=session.id, work_id=work.id, role="user", content="写章", sort_order=1)
    db_session.add(message)
    db_session.commit()
    checkpoint = CanvasCheckpoint(session_id=session.id, work_id=work.id, trigger_message_id=message.id, node_count=len(rows), edge_count=6)
    db_session.add(checkpoint)
    db_session.flush()
    for row in rows:
        db_session.add(CanvasCheckpointNode(checkpoint_id=checkpoint.id, node_id=row.id, type=row.type, title=row.title, sort_order=row.sort_order, content=row.content))
    for edge in db_session.query(Edge).all():
        db_session.add(CanvasCheckpointEdge(checkpoint_id=checkpoint.id, edge_id=edge.id, source_id=edge.source_id, target_id=edge.target_id))
    db_session.commit()
    with db_session.bind.begin() as conn:
        conn.execute(text("ALTER TABLE chapters ADD COLUMN outline_binding_id VARCHAR(36)"))
        conn.execute(text("UPDATE chapters SET outline_binding_id = 'p1'"))
        result = remove_structure_nodes(conn)
    db_session.expire_all()
    assert result["nodes_deleted"] == 5
    assert db_session.query(Node).count() == 7
    assert db_session.get(Node, "hero").content == "角色设定"
    assert db_session.get(Node, "w").content == "世界规则"
    assert db_session.get(Node, "r").content == "评审标准"
    assert db_session.get(Node, "n").content == "要求"
    assert db_session.get(Node, "c1").extra_data["characters"] == [{"id": "hero", "name": "角色"}]
    ordered, _, issues = build_chapter_catalog(db_session, work.id)
    assert [n.id for n in ordered] == ["c1", "c2", "c3"]
    assert [n.content for n in ordered] == ["正文1", "正文2", "正文3"]
    assert issues == []
    chapter = db_session.query(Chapter).one()
    assert chapter.notes == "章节笔记"
    assert "outline_binding_id" not in {c["name"] for c in inspect(db_session.bind).get_columns("chapters")}
    assert db_session.query(Edge).count() == 0
    assert db_session.query(UserCanvasAction).count() == 0
    assert db_session.query(CanvasCheckpointNode).filter(CanvasCheckpointNode.type.in_(["outline", "volume", "plot"])).count() == 0
    assert db_session.query(CanvasCheckpointEdge).count() == 0
    cp = db_session.get(CanvasCheckpoint, checkpoint.id)
    assert (cp.node_count, cp.edge_count) == (7, 0)
    assert [(n.node_id, n.sort_order) for n in db_session.query(CanvasCheckpointNode).filter_by(type="chapter").order_by(CanvasCheckpointNode.sort_order)] == [("c1", 1), ("c2", 2), ("c3", 3)]
    db_session.commit()
    with db_session.bind.begin() as conn:
        assert remove_structure_nodes(conn)["nodes_deleted"] == 0
    db_session.expire_all()
    assert [n.id for n in build_chapter_catalog(db_session, work.id)[0]] == ["c1", "c2", "c3"]
