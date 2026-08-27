"""章节排序键：从废弃 context 模块迁入 chapter_history_service。"""
from types import SimpleNamespace

from services.chapter_history_service import chapter_order_key, list_ordered_chapters


def _node(**kwargs):
    defaults = {
        "id": "n",
        "title": "",
        "extra_data": {},
        "layer": 0,
        "position_x": 0,
        "created_at": 0,
        "type": "chapter",
        "work_id": "w",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_chapter_order_key_uses_chapter_number():
    node = _node(extra_data={"chapter_number": 3}, title="随便")
    assert chapter_order_key(node)[0] == 0
    assert chapter_order_key(node)[1] == 3.0


def test_chapter_order_key_parses_title_when_extra_missing():
    node = _node(title="第 12 章 决战")
    assert chapter_order_key(node)[1] == 12.0


def test_list_ordered_chapters_sorts_by_number(db_session):
    from models.node import Node
    from models.user import User
    from models.work import CanvasWork

    user = User(username="ord", email="ord@t.t", password_hash="x")
    db_session.add(user)
    db_session.commit()
    work = CanvasWork(user_id=user.id, title="t")
    db_session.add(work)
    db_session.commit()
    later = Node(work_id=work.id, type="chapter", title="第 2 章", extra_data={"chapter_number": 2})
    earlier = Node(work_id=work.id, type="chapter", title="第 1 章", extra_data={"chapter_number": 1})
    db_session.add_all([later, earlier])
    db_session.commit()

    ordered = list_ordered_chapters(db_session, work.id)
    assert [c.extra_data["chapter_number"] for c in ordered] == [1, 2]
