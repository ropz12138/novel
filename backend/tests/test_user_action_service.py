"""user_action_service — 用户画布操作日志服务 TDD。

覆盖：
- record_node_action / record_edge_action：节点不存内容，连线 create/delete 存 preview
- has_substantial_node_change：节点 PUT 降噪（仅 position/locked 不记）
- build_pending_actions_section：水位线过滤 + 节点仅提供操作和标题
- advance_watermark：推进水位线
- list_actions：列表查询
"""
from datetime import datetime, timedelta

import pytest

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge
from models.user_canvas_action import UserCanvasAction
from services import user_action_service as svc


@pytest.fixture
def work_and_user():
    db = database.SessionLocal()
    try:
        user = User(username="action-test", email="action@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        work = CanvasWork(user_id=user.id, title="w")
        db.add(work)
        db.commit()
        db.refresh(work)
        yield db, work, user
    finally:
        db.close()


def _make_chapter(db, work, title="第一章", content="正文"):
    node = Node(work_id=work.id, type="chapter", title=title, content=content)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_edge(db, work, source, target, edge_type="登场", label=""):
    edge = Edge(work_id=work.id, source_id=source.id, target_id=target.id, edge_type=edge_type, label=label)
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


# ---------- record_node_action ----------

def test_record_node_create_does_not_store_content(work_and_user):
    db, work, user = work_and_user
    node = _make_chapter(db, work, content="林远在仓库醒来，发现周围一片漆黑。" * 20)

    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=node)

    actions = db.query(UserCanvasAction).all()
    assert len(actions) == 1
    a = actions[0]
    assert a.action_type == "create_node"
    assert a.target_id == node.id
    assert a.target_type == "chapter"
    assert a.target_title == "第一章"
    assert a.content_preview == ""


def test_record_node_delete_does_not_store_content(work_and_user):
    db, work, user = work_and_user
    node = _make_chapter(db, work, content="被删节点的内容应该留痕")

    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="delete_node", node=node)

    a = db.query(UserCanvasAction).first()
    assert a.action_type == "delete_node"
    assert a.target_title == "第一章"
    assert a.content_preview == ""


def test_record_node_update_does_not_store_content(work_and_user):
    db, work, user = work_and_user
    node = _make_chapter(db, work, content="很长的一段正文" * 50)

    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="update_node", node=node)

    a = db.query(UserCanvasAction).first()
    assert a.action_type == "update_node"
    assert a.target_title == "第一章"
    assert a.content_preview == ""


# ---------- record_edge_action ----------

def test_record_edge_create_stores_source_to_target(work_and_user):
    db, work, user = work_and_user
    src = _make_chapter(db, work, title="林川")
    tgt = _make_chapter(db, work, title="第三章")
    edge = _make_edge(db, work, src, tgt, edge_type="登场", label="首次登场")

    svc.record_edge_action(
        db, work_id=work.id, user_id=user.id, action_type="create_edge",
        edge=edge, source_title="林川", target_title="第三章",
    )

    a = db.query(UserCanvasAction).first()
    assert a.action_type == "create_edge"
    assert a.target_type == "edge"
    assert "林川" in a.target_title and "第三章" in a.target_title
    assert "登场" in a.content_preview and "首次登场" in a.content_preview


def test_record_edge_update_does_not_store_content(work_and_user):
    db, work, user = work_and_user
    src = _make_chapter(db, work, title="A")
    tgt = _make_chapter(db, work, title="B")
    edge = _make_edge(db, work, src, tgt)

    svc.record_edge_action(
        db, work_id=work.id, user_id=user.id, action_type="update_edge",
        edge=edge, source_title="A", target_title="B",
    )

    a = db.query(UserCanvasAction).first()
    assert a.action_type == "update_edge"
    assert a.content_preview == ""


# ---------- has_substantial_node_change（降噪） ----------

def test_has_substantial_node_change_filters_position_only():
    assert svc.has_substantial_node_change({"position_x": 1.0, "position_y": 2.0}) is False


def test_has_substantial_node_change_filters_locked_only():
    assert svc.has_substantial_node_change({"locked": True}) is False


def test_has_substantial_node_change_detects_title():
    assert svc.has_substantial_node_change({"title": "新标题"}) is True


def test_has_substantial_node_change_detects_content():
    assert svc.has_substantial_node_change({"content": "新内容"}) is True


def test_has_substantial_node_change_detects_chapter_elements():
    assert svc.has_substantial_node_change({"chapter_elements": []}) is True


def test_has_substantial_node_change_detects_storylines():
    assert svc.has_substantial_node_change({"storylines": []}) is True


def test_has_substantial_node_change_position_plus_title():
    assert svc.has_substantial_node_change({"position_x": 1.0, "title": "x"}) is True


# ---------- has_substantial_edge_change（边 update 降噪：跳过纯布局诊断 extra_data） ----------

def test_has_substantial_edge_change_filters_extra_data_only():
    assert svc.has_substantial_edge_change({"extra_data": {"layout_diagnostics": {"overlap": True}}}) is False


def test_has_substantial_edge_change_detects_label():
    assert svc.has_substantial_edge_change({"label": "新标签"}) is True


def test_has_substantial_edge_change_detects_edge_type():
    assert svc.has_substantial_edge_change({"edge_type": "登场"}) is True


def test_has_substantial_edge_change_extra_data_plus_label():
    assert svc.has_substantial_edge_change({"extra_data": {"x": 1}, "label": "改"}) is True


# ---------- build_pending_actions_section（水位线过滤 + 节点不提供内容） ----------

def test_build_section_returns_empty_when_no_actions(work_and_user):
    db, work, user = work_and_user
    assert svc.build_pending_actions_section(db, work.id) == ""


def test_build_section_includes_all_when_watermark_none(work_and_user):
    db, work, user = work_and_user
    node = _make_chapter(db, work, title="主角", content="觉醒")
    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=node)

    section = svc.build_pending_actions_section(db, work.id)

    assert '我新增了「主角」节点。' in section
    assert "觉醒" not in section


def test_build_section_filters_actions_before_watermark(work_and_user):
    db, work, user = work_and_user
    base = datetime(2025, 1, 1, 12, 0, 0)

    node = _make_chapter(db, work, title="旧节点", content="旧")
    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=node)
    old = db.query(UserCanvasAction).first()
    old.created_at = base
    db.commit()

    work.canvas_action_watermark = base + timedelta(seconds=1)
    db.commit()

    section = svc.build_pending_actions_section(db, work.id)
    assert section == ""


def test_build_section_shows_only_after_watermark(work_and_user):
    db, work, user = work_and_user
    base = datetime(2025, 1, 1, 12, 0, 0)

    n1 = _make_chapter(db, work, title="旧操作", content="旧")
    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=n1)
    db.query(UserCanvasAction).first().created_at = base

    work.canvas_action_watermark = base + timedelta(seconds=1)
    db.commit()

    n2 = _make_chapter(db, work, title="新操作", content="新")
    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=n2)
    db.query(UserCanvasAction).filter(UserCanvasAction.target_title == "新操作").first().created_at = base + timedelta(seconds=2)
    db.commit()

    section = svc.build_pending_actions_section(db, work.id)
    assert "新操作" in section
    assert "旧操作" not in section


def test_build_section_update_only_reports_node_title(work_and_user):
    db, work, user = work_and_user
    node = _make_chapter(db, work, title="第三章", content="非常长的修改后正文" * 50)
    svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="update_node", node=node)

    section = svc.build_pending_actions_section(db, work.id)

    assert '我修改了「第三章」节点。' in section
    assert "read_node_content" not in section
    assert "非常长的修改后正文" not in section


def test_build_section_edge_update_guides_to_query_edges(work_and_user):
    db, work, user = work_and_user
    src = _make_chapter(db, work, title="A")
    tgt = _make_chapter(db, work, title="B")
    edge = _make_edge(db, work, src, tgt)
    svc.record_edge_action(
        db, work_id=work.id, user_id=user.id, action_type="update_edge",
        edge=edge, source_title="A", target_title="B",
    )

    section = svc.build_pending_actions_section(db, work.id)

    assert "修改" in section
    assert "query_edges" in section  # 引导语


# ---------- advance_watermark ----------

def test_advance_watermark_sets_timestamp(work_and_user):
    db, work, user = work_and_user
    ts = datetime(2025, 6, 1, 10, 0, 0)
    svc.advance_watermark(db, work.id, ts)
    db.refresh(work)
    assert work.canvas_action_watermark == ts


def test_advance_watermark_none_work_id_noop(work_and_user):
    db, work, user = work_and_user
    svc.advance_watermark(db, None, datetime.utcnow())  # 不应抛异常
    db.refresh(work)
    assert work.canvas_action_watermark is None


# ---------- list_actions ----------

def test_list_actions_returns_newest_first(work_and_user):
    db, work, user = work_and_user
    base = datetime(2025, 1, 1, 12, 0, 0)
    for i in range(3):
        n = _make_chapter(db, work, title=f"节点{i}", content="x")
        svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=n)
        db.query(UserCanvasAction).filter(UserCanvasAction.target_title == f"节点{i}").first().created_at = base + timedelta(seconds=i)
    db.commit()

    actions = svc.list_actions(db, work.id, limit=10)
    assert len(actions) == 3
    titles = [a["target_title"] for a in actions]
    assert titles == ["节点2", "节点1", "节点0"]  # 最新在前


def test_list_actions_respects_limit(work_and_user):
    db, work, user = work_and_user
    for i in range(5):
        n = _make_chapter(db, work, title=f"n{i}", content="x")
        svc.record_node_action(db, work_id=work.id, user_id=user.id, action_type="create_node", node=n)

    actions = svc.list_actions(db, work.id, limit=2)
    assert len(actions) == 2
