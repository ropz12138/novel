from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import SupervisorAgent


def test_load_work_notes_returns_all_latest_note_content_in_stable_order(db_session, monkeypatch):
    user = User(username="note-injection", email="note-injection@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="笔记注入测试")
    db_session.add(work)
    db_session.flush()
    db_session.add_all([
        Node(work_id=work.id, type="note", title="后写", content="第二条完整内容", sort_order=2),
        Node(work_id=work.id, type="chapter", title="正文", content="不能混入", sort_order=1),
        Node(work_id=work.id, type="note", title="先写", content="第一条完整内容", sort_order=1),
    ])
    db_session.commit()

    class SessionProxy:
        def query(self, *args, **kwargs):
            return db_session.query(*args, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr("services.agents.supervisor._get_db", lambda: SessionProxy())

    context = SupervisorAgent()._load_work_note_context(work.id)

    assert context.index("先写") < context.index("后写")
    assert "第一条完整内容" in context
    assert "第二条完整内容" in context
    assert "不能混入" not in context

