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


def test_copy_volume_moves_descendants_characters_and_notes(mock_auth):
    db = database.SessionLocal()
    try:
        source = _work(db, mock_auth.id, "源")
        target = _work(db, mock_auth.id, "目标")
        _node(db, target.id, "volume", "已有卷", 4)
        _node(db, target.id, "character", "旧人", 4, scope="minor", content="原来的人")

        outline = _node(db, source.id, "outline", "总纲", 1, content="全书")
        volume = _node(
            db, source.id, "volume", "第一卷", 1,
            content="卷简介", layer=2, locked=True, position_x=12, position_y=34,
        )
        other_volume = _node(db, source.id, "volume", "第二卷", 2)
        opening = _node(db, source.id, "plot", "开端", 1, content="起")
        turn = _node(db, source.id, "plot", "转折", 2, content="转")
        body = "甲" * 400
        anan = _node(
            db, source.id, "character", "阿楠", 1,
            scope="major", content="配角简介",
        )
        hero = _node(
            db, source.id, "character", "林舟", 8,
            scope="global", content="主角简介",
            extra_data={"storylines": [{"name": "身世", "description": "被逐", "body": ["离开村子"]}]},
        )
        _node(db, source.id, "character", "路人", 3, scope="temp", content="不引用")
        _node(db, source.id, "note", "写作要求", 1, scope="global", content="短句要多")
        chapter = _node(
            db, source.id, "chapter", "第一章", 1, content=body,
            extra_data={
                "chapter_elements": [{"title": "进城", "content": "见到旧人", "priority": "high"}],
                "characters": [
                    {"id": anan.id, "name": "阿楠"},
                    {"id": hero.id, "name": "林舟"},
                ],
            },
        )
        sequel = _node(
            db, source.id, "chapter", "第二章", 2, content="后续",
            extra_data={"characters": [
                {"id": hero.id, "name": "林舟"},
                {"id": "missing-character", "name": "已删除"},
            ]},
        )
        db.add(Chapter(
            work_id=source.id, node_id=chapter.id, title="第一章",
            content=body, notes="作者要求：雨夜",
        ))
        db.add(Chapter(
            work_id=source.id, node_id=sequel.id, title="第二章",
            content="后续", notes="保留伏笔",
        ))
        db.add(ChapterIllustration(
            work_id=source.id, node_id=chapter.id, file_path="/tmp/rain.png",
            prompt="雨", insert_after_paragraph=0,
        ))
        db.add(NodeContentDiffState(
            node_id=chapter.id, work_id=source.id, baseline_content="旧稿",
        ))
        _edge(db, source.id, outline.id, volume.id)
        _edge(db, source.id, outline.id, other_volume.id)
        opening_edge = _edge(
            db, source.id, volume.id, opening.id,
            edge_type="contains", label="开篇",
            extra_data={"layout": {"source_side": "bottom", "target_side": "top"}},
        )
        _edge(db, source.id, volume.id, turn.id, edge_type="contains")
        _edge(db, source.id, opening.id, chapter.id, edge_type="contains")
        _edge(db, source.id, turn.id, sequel.id, edge_type="contains")
        _edge(db, source.id, chapter.id, sequel.id, edge_type="next")
        source_count = db.query(Node).filter_by(work_id=source.id).count()
        db.commit()
        opening_edge_id = opening_edge.id

        response = client.post(
            f"/api/nodes/{volume.id}/copy",
            json={"target_work_id": target.id},
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["target_work_id"] == target.id
        assert payload["omitted_character_refs"] == ["missing-character"]
        assert {node["title"] for node in payload["nodes"]} == {
            "第一卷", "开端", "转折", "第一章", "第二章", "阿楠", "林舟",
        }

        db.expire_all()
        assert db.query(Node).filter_by(work_id=source.id).count() == source_count
        assert db.get(Node, chapter.id).extra_data["characters"] == [
            {"id": anan.id, "name": "阿楠"},
            {"id": hero.id, "name": "林舟"},
        ]
        assert db.get(Edge, opening_edge_id).label == "开篇"

        copied = {node.title: node for node in db.query(Node).filter_by(work_id=target.id)}
        assert set(copied) == {
            "已有卷", "旧人", "第一卷", "开端", "转折", "第一章", "第二章", "阿楠", "林舟",
        }
        assert copied["第一卷"].sort_order == 5
        assert copied["第一卷"].locked is False
        assert copied["第一卷"].layer == 2
        assert copied["第一卷"].content == "卷简介"
        assert copied["第一卷"].position_x == 0
        assert copied["第一卷"].position_y == 0
        assert copied["第一卷"].id != volume.id
        assert copied["开端"].sort_order == 1
        assert copied["转折"].sort_order == 2
        assert copied["阿楠"].sort_order == 5
        assert copied["阿楠"].scope == "major"
        assert copied["阿楠"].content == "配角简介"
        assert copied["林舟"].sort_order == 6
        assert copied["林舟"].scope == "global"
        assert copied["林舟"].extra_data["storylines"] == [
            {"name": "身世", "description": "被逐", "body": ["离开村子"]},
        ]
        assert copied["旧人"].content == "原来的人"
        assert copied["第一章"].content == body
        assert copied["第一章"].extra_data["chapter_elements"] == [
            {"title": "进城", "content": "见到旧人", "priority": "high"},
        ]
        assert copied["第一章"].extra_data["characters"] == [
            {"id": copied["阿楠"].id, "name": "阿楠"},
            {"id": copied["林舟"].id, "name": "林舟"},
        ]
        assert copied["第二章"].extra_data["characters"] == [
            {"id": copied["林舟"].id, "name": "林舟"},
        ]
        first_chapter = db.query(Chapter).filter_by(node_id=copied["第一章"].id).one()
        assert first_chapter.work_id == target.id
        assert first_chapter.content == body
        assert first_chapter.notes == "作者要求：雨夜"
        assert first_chapter.outline_binding_id is None
        assert db.query(Chapter).filter_by(node_id=copied["第二章"].id).one().notes == "保留伏笔"
        assert db.query(ChapterIllustration).filter_by(work_id=target.id).count() == 0
        assert db.query(ChapterIllustration).filter_by(node_id=chapter.id).count() == 1
        assert db.query(NodeContentDiffState).filter_by(work_id=target.id).count() == 0
        assert db.query(NodeContentDiffState).filter_by(node_id=chapter.id).count() == 1

        pairs = {
            (db.get(Node, edge.source_id).title, db.get(Node, edge.target_id).title, edge.label)
            for edge in db.query(Edge).filter_by(work_id=target.id)
        }
        assert pairs == {
            ("第一卷", "开端", "开篇"),
            ("第一卷", "转折", ""),
            ("开端", "第一章", ""),
            ("转折", "第二章", ""),
        }
        copied_opening = next(
            edge for edge in db.query(Edge).filter_by(work_id=target.id)
            if edge.label == "开篇"
        )
        assert copied_opening.id != opening_edge_id
        assert copied_opening.edge_type == "contains"
        assert copied_opening.extra_data["layout"]["source_side"] == "bottom"
        assert db.query(Edge).filter_by(target_id=copied["第一卷"].id).count() == 0

        actions = db.query(UserCanvasAction).filter_by(work_id=target.id).all()
        assert sorted(action.action_type for action in actions) == (
            ["create_edge"] * 4 + ["create_node"] * 7
        )
        assert db.query(UserCanvasAction).filter_by(work_id=source.id).count() == 0
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
