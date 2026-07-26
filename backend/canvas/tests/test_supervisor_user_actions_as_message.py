"""用户操作改为独立 user 消息注入（不再写 system prompt）— TDD。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.routers.auth import get_current_user
from app.services.agents.supervisor import SupervisorAgent
from app.services.session_store import session_store
from app.services import user_action_service as svc

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="msg-inject", email="msg@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


# ---------- _load_chat_history 分离当前轮 user ----------

def test_load_chat_history_separates_current_turn_users(mock_auth):
    db = database.SessionLocal()
    try:
        session = session_store.create_session(user_id=mock_auth.id, work_id=None)
        sid = session["id"]
        # 历史：一问一答
        session_store.add_message(sid, "user", "上一轮问题")
        session_store.add_message(sid, "assistant", "上一轮回答")
        # 当前轮：操作消息 + 用户文字（两条 user 连续在末尾）
        session_store.add_message(sid, "user", "【操作摘要】删除节点X", meta={"type": "user_canvas_actions"})
        session_store.add_message(sid, "user", "你知道我做了什么吗")
    finally:
        db.close()

    agent = SupervisorAgent()
    history, current_turn = agent._load_chat_history(sid)

    # history 不含当前轮两条 user
    history_roles = [getattr(m, "type", "") for m in history]
    history_contents = [getattr(m, "content", "") for m in history]
    assert all("【操作摘要】" not in c for c in history_contents)
    assert all("你知道我做了什么吗" not in c for c in history_contents)
    # current_turn 含两条，操作在前、文字在后
    assert len(current_turn) == 2
    assert current_turn[0]["content"] == "【操作摘要】删除节点X"
    assert current_turn[1]["content"] == "你知道我做了什么吗"


def test_load_chat_history_single_user_current_turn(mock_auth):
    db = database.SessionLocal()
    try:
        session = session_store.create_session(user_id=mock_auth.id)
        sid = session["id"]
        session_store.add_message(sid, "assistant", "历史回答")
        session_store.add_message(sid, "user", "只有文字")
    finally:
        db.close()

    agent = SupervisorAgent()
    history, current_turn = agent._load_chat_history(sid)
    assert len(current_turn) == 1
    assert current_turn[0]["content"] == "只有文字"


def test_load_chat_history_no_current_user(mock_auth):
    db = database.SessionLocal()
    try:
        session = session_store.create_session(user_id=mock_auth.id)
        sid = session["id"]
        session_store.add_message(sid, "user", "问")
        session_store.add_message(sid, "assistant", "答")
    finally:
        db.close()

    agent = SupervisorAgent()
    history, current_turn = agent._load_chat_history(sid)
    assert current_turn == []


# ---------- system prompt 不再含操作 ----------

def test_build_system_prompt_no_longer_accepts_user_actions_section():
    agent = SupervisorAgent()
    prompt = agent._build_system_prompt()
    assert "{context_section}" not in prompt
    assert "画布操作" not in prompt


# ---------- /start 存消息顺序 + 标题不被操作污染 ----------

def test_start_stores_actions_message_before_user_text(mock_auth, monkeypatch):
    db = database.SessionLocal()
    work_id = None
    try:
        work = CanvasWork(user_id=mock_auth.id, title="新对话")  # 模拟默认标题
        db.add(work)
        db.commit()
        db.refresh(work)
        work_id = work.id
        node = Node(work_id=work.id, type="chapter", title="第6章", content="碎片")
        db.add(node)
        db.commit()
        db.refresh(node)
        svc.record_node_action(db, work_id=work.id, user_id=mock_auth.id, action_type="delete_node", node=node)
    finally:
        db.close()

    async def fake_run(msg, context, emit=None):
        pass
    from app.routers import supervisor as sup_router
    monkeypatch.setattr(sup_router.supervisor_agent, "run", fake_run)
    monkeypatch.setattr(sup_router, "_capture_checkpoint_before_agent", lambda *a, **k: None)
    monkeypatch.setattr(sup_router, "SessionLocal", database.SessionLocal)

    resp = client.post("/api/supervisor/start", json={"message": "你知道我做了什么吗", "work_id": work_id})
    assert resp.status_code == 200

    # 取 session 的消息，验证顺序
    db2 = database.SessionLocal()
    try:
        sid = db2.query(User).filter_by(id=mock_auth.id).first()
        from app.models.session import SupervisorSession, SupervisorMessage
        sess = db2.query(SupervisorSession).order_by(SupervisorSession.created_at.desc()).first()
        msgs = db2.query(SupervisorMessage).filter(SupervisorMessage.session_id == sess.id).order_by(SupervisorMessage.sort_order.asc()).all()
        # 末尾应是：操作消息(在前) + 用户文字(在后)
        last_two = msgs[-2:]
        assert last_two[0].role == "user"
        assert (last_two[0].meta or {}).get("type") == "user_canvas_actions"
        assert last_two[1].role == "user"
        assert last_two[1].content == "你知道我做了什么吗"
        # 标题应是用户文字，不是操作摘要
        assert sess.title == "你知道我做了什么吗"
    finally:
        db2.close()


def test_start_no_actions_stores_only_user_text(mock_auth, monkeypatch):
    db = database.SessionLocal()
    work_id = None
    try:
        work = CanvasWork(user_id=mock_auth.id, title="新对话")
        db.add(work)
        db.commit()
        db.refresh(work)
        work_id = work.id
    finally:
        db.close()

    async def fake_run(msg, context, emit=None):
        pass
    from app.routers import supervisor as sup_router
    monkeypatch.setattr(sup_router.supervisor_agent, "run", fake_run)
    monkeypatch.setattr(sup_router, "_capture_checkpoint_before_agent", lambda *a, **k: None)
    monkeypatch.setattr(sup_router, "SessionLocal", database.SessionLocal)

    resp = client.post("/api/supervisor/start", json={"message": "你好", "work_id": work_id})
    assert resp.status_code == 200

    db2 = database.SessionLocal()
    try:
        from app.models.session import SupervisorSession, SupervisorMessage
        sess = db2.query(SupervisorSession).order_by(SupervisorSession.created_at.desc()).first()
        user_msgs = db2.query(SupervisorMessage).filter(
            SupervisorMessage.session_id == sess.id, SupervisorMessage.role == "user"
        ).all()
        # 无操作时只有一条 user 消息（用户文字），没有操作消息
        assert len(user_msgs) == 1
        assert (user_msgs[0].meta or {}).get("type") != "user_canvas_actions"
    finally:
        db2.close()


# ---------- agent 成功后推进水位线 ----------

def test_start_advances_watermark_after_success(mock_auth, monkeypatch):
    db = database.SessionLocal()
    work_id = None
    try:
        work = CanvasWork(user_id=mock_auth.id, title="w")
        db.add(work)
        db.commit()
        db.refresh(work)
        work_id = work.id
        assert work.canvas_action_watermark is None
    finally:
        db.close()

    async def fake_run(msg, context, emit=None):
        pass
    from app.routers import supervisor as sup_router
    monkeypatch.setattr(sup_router.supervisor_agent, "run", fake_run)
    monkeypatch.setattr(sup_router, "_capture_checkpoint_before_agent", lambda *a, **k: None)
    monkeypatch.setattr(sup_router, "SessionLocal", database.SessionLocal)

    client.post("/api/supervisor/start", json={"message": "你好", "work_id": work_id})

    db2 = database.SessionLocal()
    try:
        w = db2.query(CanvasWork).filter(CanvasWork.id == work_id).first()
        assert w.canvas_action_watermark is not None  # 成功后推进
    finally:
        db2.close()
