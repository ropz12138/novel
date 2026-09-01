"""节点内容查询的作品隔离测试。"""
import json
import importlib

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork

qt = importlib.import_module("services.agents.tools.query_tools")


def _make_work(db, title="work"):
    user = User(username=f"u-{title}", email=f"{title}@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    return work


def test_read_node_content_is_scoped_to_work(monkeypatch):
    db = database.SessionLocal()
    try:
        work1 = _make_work(db, "one")
        work2 = _make_work(db, "two")
        foreign = Node(sort_order=0, work_id=work2.id, type="idea", title="其他作品", content="secret")
        db.add(foreign)
        db.commit()
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work1.id)

        result = json.loads(qt._read_node_content_sync([foreign.id]))

        assert result["error"] == "未找到节点"
    finally:
        db.close()
