"""Supervisor 系统提示词不注入已下线的全局设定段落。"""
import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from services.agents.supervisor import SupervisorAgent


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_supervisor_prompt_excludes_global_context():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        note = Node(sort_order=0, work_id=work.id, type="note", title="硬汉派", content="简洁有力的对白")
        world = Node(sort_order=0, work_id=work.id, type="worldbuilding", title="赛博朋克", content="高科技低生活")
        db.add_all([note, world])
        db.commit()

        prompt = SupervisorAgent()._build_system_prompt()
        assert "全局设定" not in prompt
        assert "硬汉派" not in prompt
        assert "简洁有力的对白" not in prompt
        assert "赛博朋克" not in prompt
        assert "高科技低生活" not in prompt
    finally:
        db.close()


def test_supervisor_prompt_no_global_section():
    prompt = SupervisorAgent()._build_system_prompt()
    assert "全局设定" not in prompt
