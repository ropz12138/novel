"""REST 写操作 hook → 用户操作日志 TDD。

验证：用户经 REST API 增删改节点/边时，会留下 user_canvas_action 记录；
节点 PUT 仅坐标/锁定变化时不记录（降噪）。
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.user_canvas_action import UserCanvasAction

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="hook-test", email="hook@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_work(db, user_id):
    work = CanvasWork(user_id=user_id, title="w")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


def _actions(db, work_id):
    return db.query(UserCanvasAction).filter(UserCanvasAction.work_id == work_id).all()


# ---------- 节点 ----------

def test_content_diff_api_restores_and_reviews_exact_agent_groups(mock_auth):
    from models.node import Node
    from services.chapter_edit_service import build_replacement_diff
    from services.node_agent_diff import record_change
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        old = "A\n\nB\n\nC"
        new = "X\n\nA′\n\nB′\n\nC′"
        node = Node(work_id=work.id, type="plot", title="原始分组", content=new, sort_order=1)
        db.add(node)
        db.flush()
        record_change(db, node, old, build_replacement_diff(old, [
            {"old": "A", "new": "X\n\nA′"}, {"old": "B", "new": "B′"}, {"old": "C", "new": "C′"}]))
        db.commit()
        response = client.get(f"/api/works/{work.id}/content-diffs")
        assert response.status_code == 200
        snapshot = response.json()[0]
        assert snapshot["grouping"] == "agent_replacements"
        assert [(h["old_text"], h["new_text"]) for h in snapshot["hunks"]] == [
            ("A", "X\n\nA′"), ("B", "B′"), ("C", "C′")]
        response = client.put(f"/api/nodes/{node.id}/content-diff-decision", json={
            "expected_content": new, "expected_baseline": old,
            "baseline_content": old, "current_content": old, "groups": [],
        })
        assert response.status_code == 200
        assert response.json()["hunks"] == []
        assert client.get(f"/api/works/{work.id}/content-diffs").json() == []
    finally:
        db.close()

def test_create_node_via_rest_logs_action(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        res = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "第一章", "content": "正文内容"},
        )
        assert res.status_code == 201
        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "create_node"
        assert actions[0].target_title == "第一章"
        assert actions[0].content_preview == ""
    finally:
        db.close()


def test_delete_node_via_rest_logs_action_without_content(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        create_res = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "待删", "content": "被删内容留痕"},
        )
        node_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()  # 清掉 create 的记录，只看 delete
        db.commit()

        client.delete(f"/api/nodes/{node_id}")

        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "delete_node"
        assert actions[0].target_title == "待删"
        assert actions[0].content_preview == ""
    finally:
        db.close()


def test_update_node_title_via_rest_logs_action(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        create_res = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "原标题", "content": "原内容"},
        )
        node_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        client.put(f"/api/nodes/{node_id}", json={"title": "新标题"})

        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "update_node"
        assert actions[0].target_title == "新标题"
        assert actions[0].content_preview == ""  # update 不记内容
    finally:
        db.close()


def test_update_node_content_accepts_matching_expected_content(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        node_id = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "第一章", "content": "旧正文"},
        ).json()["id"]

        response = client.put(
            f"/api/nodes/{node_id}",
            json={"content": "新正文", "expected_content": "旧正文"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "新正文"
    finally:
        db.close()


def test_update_node_content_rejects_stale_expected_content(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        node_id = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "第一章", "content": "服务器新正文"},
        ).json()["id"]

        response = client.put(
            f"/api/nodes/{node_id}",
            json={"content": "用户编辑正文", "expected_content": "用户打开时正文"},
        )

        assert response.status_code == 409
        assert "正文已发生变化" in response.json()["detail"]
    finally:
        db.close()


def test_update_node_position_only_does_not_log(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        create_res = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "n", "content": ""},
        )
        node_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        client.put(f"/api/nodes/{node_id}", json={"position_x": 100.0, "position_y": 200.0})

        assert _actions(db, work.id) == []  # 降噪
    finally:
        db.close()


def test_update_node_locked_only_does_not_log(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        create_res = client.post(
            f"/api/works/{work.id}/nodes",
            json={"sort_order": 1, "type": "chapter", "title": "n", "content": ""},
        )
        node_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        client.put(f"/api/nodes/{node_id}", json={"locked": True})

        assert _actions(db, work.id) == []
    finally:
        db.close()


# ---------- 边 ----------

def _make_two_nodes(work_id):
    db = database.SessionLocal()
    try:
        # 画布连线使用合法的 plot → chapter 父子关系。
        a = client.post(f"/api/works/{work_id}/nodes", json={"sort_order": 1, "type": "plot", "title": "源", "content": ""}).json()
        b = client.post(f"/api/works/{work_id}/nodes", json={"sort_order": 2, "type": "chapter", "title": "目标", "content": ""}).json()
        return a["id"], b["id"]
    finally:
        db.close()


def test_create_edge_via_rest_logs_action(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        src, tgt = _make_two_nodes(work.id)
        db.query(UserCanvasAction).delete()
        db.commit()

        res = client.post(
            f"/api/works/{work.id}/edges",
            json={"source_id": src, "target_id": tgt, "edge_type": "登场", "label": "首次"},
        )
        assert res.status_code == 201
        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "create_edge"
        assert "源" in actions[0].target_title and "目标" in actions[0].target_title
        assert "登场" in actions[0].content_preview
    finally:
        db.close()


def test_delete_edge_via_rest_logs_action(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        src, tgt = _make_two_nodes(work.id)
        create_res = client.post(
            f"/api/works/{work.id}/edges",
            json={"source_id": src, "target_id": tgt, "edge_type": "推进"},
        )
        edge_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        client.delete(f"/api/edges/{edge_id}")

        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "delete_edge"
        assert "推进" in actions[0].content_preview
    finally:
        db.close()


def test_update_edge_via_rest_logs_action(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        src, tgt = _make_two_nodes(work.id)
        create_res = client.post(
            f"/api/works/{work.id}/edges",
            json={"source_id": src, "target_id": tgt, "edge_type": "推进"},
        )
        edge_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        client.put(f"/api/edges/{edge_id}", json={"label": "新标签"})

        actions = _actions(db, work.id)
        assert len(actions) == 1
        assert actions[0].action_type == "update_edge"
        assert actions[0].content_preview == ""
    finally:
        db.close()


def test_update_edge_extra_data_only_does_not_log(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        src, tgt = _make_two_nodes(work.id)
        create_res = client.post(
            f"/api/works/{work.id}/edges",
            json={"source_id": src, "target_id": tgt, "edge_type": "推进"},
        )
        edge_id = create_res.json()["id"]
        db.query(UserCanvasAction).delete()
        db.commit()

        # 前端自动布局诊断只写 extra_data —— 不应记为用户操作
        client.put(
            f"/api/edges/{edge_id}",
            json={"extra_data": {"layout_diagnostics": {"overlap": True, "layout_version": 3}}},
        )

        assert _actions(db, work.id) == []
    finally:
        db.close()
