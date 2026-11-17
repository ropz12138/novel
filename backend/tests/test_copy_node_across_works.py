"""跨作品复制节点。

复制选中节点、其父子层级下的全部下级，以及这些章节仍能找到的角色。
角色 id 改写到目标作品的新角色上。子树之外的连线、插图和正文修改记录不复制。
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from models.chapter import Chapter
from models.chapter_illustration import ChapterIllustration
from models.edge import Edge
from models.node import Node
from models.node_content_diff_state import NodeContentDiffState
from models.user import User
from models.user_canvas_action import UserCanvasAction
from models.work import CanvasWork
from routers.auth import get_current_user

client = TestClient(app)


@pytest.fixture
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="copy-owner", email="copy-owner@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _work(db, user_id, title):
    work = CanvasWork(user_id=user_id, title=title)
    db.add(work)
    db.flush()
    return work


def _node(db, work_id, node_type, title, sort_order, **kwargs):
    node = Node(
        work_id=work_id,
        type=node_type,
        title=title,
        sort_order=sort_order,
        **kwargs,
    )
    db.add(node)
    db.flush()
    return node


def _edge(db, work_id, source_id, target_id, **kwargs):
    edge = Edge(work_id=work_id, source_id=source_id, target_id=target_id, **kwargs)
    db.add(edge)
    db.flush()
    return edge


def test_copy_chapter_preserves_characters_and_notes(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        hero = _node(db, source.id, "character", "林舟", 1, content="角色设定", scope="major")
        chapter = _node(db, source.id, "chapter", "第一章", 1, content="完整正文", extra_data={
            "characters": [{"id": hero.id, "name": hero.title}],
            "keep": True,
            "chapter_elements": [{"title": "开场", "content": "事件"}],
        })
        db.add(Chapter(work_id=source.id, node_id=chapter.id, content=chapter.content, notes="完整章节笔记"))
        db.commit()
        response = client.post(f"/api/nodes/{chapter.id}/copy", json={"target_work_id": target.id})
        assert response.status_code == 201, response.text
        copied = {n.type: n for n in db.query(Node).filter_by(work_id=target.id)}
        assert set(copied) == {"chapter", "character"}
        assert copied["chapter"].content == "完整正文"
        assert copied["character"].content == "角色设定"
        assert copied["chapter"].extra_data["characters"][0]["id"] == copied["character"].id
        assert "chapter_elements" not in (copied["chapter"].extra_data or {})
        assert copied["chapter"].extra_data.get("keep") is True
        assert copied["character"].id != hero.id
        assert db.query(Chapter).filter_by(node_id=copied["chapter"].id).one().notes == "完整章节笔记"
        assert response.json()["edges"] == []
    finally:
        db.close()


def test_copy_chapter_does_not_keep_its_parent_edge(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        _node(db, target.id, "chapter", "已有章", 3, content="旧")
        plot = _node(db, source.id, "plot", "情节", 1)
        chapter = _node(db, source.id, "chapter", "第一章", 1, content="正文")
        _edge(db, source.id, plot.id, chapter.id)
        db.commit()

        response = client.post(
            f"/api/nodes/{chapter.id}/copy",
            json={"target_work_id": target.id},
        )
        assert response.status_code == 201, response.text
        copied = {
            node.title: node
            for node in db.query(Node).filter_by(work_id=target.id)
        }
        assert set(copied) == {"已有章", "第一章"}
        assert copied["第一章"].sort_order == 4
        assert copied["第一章"].content == "正文"
        assert db.query(Edge).filter_by(work_id=target.id).count() == 0
        assert db.query(Node).filter_by(work_id=source.id).count() == 2
    finally:
        db.close()


def test_copy_character_keeps_scope_and_appends_sort_order(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        _node(db, target.id, "character", "已有角色", 9, scope="minor")
        hero = _node(
            db, source.id, "character", "林舟", 2,
            scope="major", content="简介",
            extra_data={"storylines": [{"name": "力量", "description": "", "body": ["觉醒"]}]},
        )
        db.commit()

        response = client.post(
            f"/api/nodes/{hero.id}/copy",
            json={"target_work_id": target.id},
        )
        assert response.status_code == 201, response.text
        copied = db.query(Node).filter_by(work_id=target.id, title="林舟").one()
        assert copied.scope == "major"
        assert copied.content == "简介"
        assert copied.sort_order == 10
        assert copied.extra_data["storylines"][0]["name"] == "力量"
        assert db.query(Edge).filter_by(work_id=target.id).count() == 0
    finally:
        db.close()


def test_copy_note_copies_only_that_node(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        _node(db, target.id, "note", "旧笔记", 3, scope="global")
        note = _node(db, source.id, "note", "写作要求", 1, scope="global", content="短句。")
        other = _node(db, source.id, "worldbuilding", "世界观", 1, scope="global", content="不一起走")
        db.commit()

        response = client.post(
            f"/api/nodes/{note.id}/copy",
            json={"target_work_id": target.id},
        )
        assert response.status_code == 201, response.text
        copied = {node.title: node for node in db.query(Node).filter_by(work_id=target.id)}
        assert set(copied) == {"旧笔记", "写作要求"}
        assert copied["写作要求"].content == "短句。"
        assert copied["写作要求"].scope == "global"
        assert copied["写作要求"].sort_order == 4
        assert db.get(Node, other.id).work_id == source.id
    finally:
        db.close()


def test_copy_worldbuilding_copies_only_that_node(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        _node(db, target.id, "worldbuilding", "旧设定", 2, scope="global", content="原有")
        world = _node(db, source.id, "worldbuilding", "灵气体系", 1, scope="global", content="天地有灵。")
        _node(db, source.id, "note", "写作要求", 1, scope="global", content="不一起走")
        _node(db, source.id, "character", "林舟", 1, scope="global", content="也不一起走")
        db.commit()

        response = client.post(
            f"/api/nodes/{world.id}/copy",
            json={"target_work_id": target.id},
        )
        assert response.status_code == 201, response.text
        copied = {node.title: node for node in db.query(Node).filter_by(work_id=target.id)}
        assert set(copied) == {"旧设定", "灵气体系"}
        assert copied["灵气体系"].content == "天地有灵。"
        assert copied["灵气体系"].scope == "global"
        assert copied["灵气体系"].sort_order == 3
        assert copied["灵气体系"].id != world.id
        assert db.query(Node).filter_by(work_id=source.id).count() == 3
    finally:
        db.close()


def test_copy_rejects_same_work(mock_auth):
    db = database.SessionLocal()
    try:
        work = _work(db, mock_auth.id, "只有这一部")
        note = _node(db, work.id, "note", "笔记", 1, scope="global", content="原文")
        db.commit()

        response = client.post(
            f"/api/nodes/{note.id}/copy",
            json={"target_work_id": work.id},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "不能复制到当前作品"
        assert db.query(Node).filter_by(work_id=work.id).count() == 1
    finally:
        db.close()


def test_copy_rejects_missing_node_and_foreign_works(mock_auth):
    db = database.SessionLocal()
    try:
        other = User(username="copy-other", email="copy-other@test.dev", password_hash="x")
        db.add(other)
        db.flush()
        mine = _work(db, mock_auth.id, "我的")
        foreign = _work(db, other.id, "别人的")
        my_note = _node(db, mine.id, "note", "我的笔记", 1, scope="global", content="可以看")
        secret = _node(db, foreign.id, "note", "秘密", 1, scope="global", content="不能看")
        db.commit()

        missing = client.post(
            "/api/nodes/missing-node/copy",
            json={"target_work_id": mine.id},
        )
        assert missing.status_code == 404

        foreign_target = client.post(
            f"/api/nodes/{my_note.id}/copy",
            json={"target_work_id": foreign.id},
        )
        assert foreign_target.status_code == 404
        assert db.query(Node).filter_by(work_id=foreign.id).count() == 1

        foreign_source = client.post(
            f"/api/nodes/{secret.id}/copy",
            json={"target_work_id": mine.id},
        )
        assert foreign_source.status_code == 404
        assert db.query(Node).filter_by(work_id=mine.id).count() == 1
        assert db.get(Node, secret.id).content == "不能看"
    finally:
        db.close()
