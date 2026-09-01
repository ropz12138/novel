"""Node.layer 字段测试 — TDD：驱动 layer 字段的引入。

layer 为整数，驱动前端垂直布局。约定：数字小的在上，同 layer 排一行。
"""
import database
from models.user import User
from models.work import CanvasWork
from models.node import Node


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="测试作品")
    db.add(work)
    db.commit()
    return work


def test_node_layer_default_zero():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="idea", title="灵感")
        db.add(node)
        db.commit()
        db.refresh(node)
        assert node.layer == 0
    finally:
        db.close()


def test_node_layer_persisted():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="outline", title="主线", layer=2)
        db.add(node)
        db.commit()
        fetched = db.query(Node).filter_by(id=node.id).first()
        assert fetched is not None
        assert fetched.layer == 2
    finally:
        db.close()
