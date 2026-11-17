"""章节独立排序，旧层级类型不会再产生父子边。"""
import json
import pytest
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.tools import node_tools as nt
from services.edge_relation import derive_relation_kind, validate_relation_types, validate_hierarchy_structure


def test_chapter_has_no_parent_level():
    for removed in ("outline", "volume", "plot"):
        assert derive_relation_kind(removed, "chapter") is None
        assert derive_relation_kind("chapter", removed) is None
    assert derive_relation_kind("chapter", "chapter") is None
    assert "sort_order" in validate_relation_types("chapter", "chapter")


@pytest.mark.parametrize("batch", [False, True])
def test_chapter_sequence_edges_are_rejected(db_session, monkeypatch, batch):
    user = User(username="edges", email="edges@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="独立章节")
    db_session.add(work)
    db_session.flush()
    nodes = [Node(work_id=work.id, type="chapter", title=f"章{i}", sort_order=i) for i in (1, 2)]
    db_session.add_all(nodes)
    db_session.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    assert validate_hierarchy_structure(db_session, work.id, nodes[0], nodes[0])
    if batch:
        result = nt._batch_create_edges_sync([{"source_id": nodes[0].id, "target_id": nodes[1].id, "edge_type": "接续"}])
    else:
        result = nt._create_edge_sync(nodes[0].id, nodes[1].id, edge_type="接续")
    assert "error" in json.loads(result)
    assert "sort_order" in result
