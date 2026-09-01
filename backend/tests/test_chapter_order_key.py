"""章节排序键：顺序只认 sort_order。

此前从 extra_data 序号、标题「第N章」正则与坐标逐级推断，同一份顺序有多个
来源，彼此可能矛盾。改为创建时必填的 sort_order 之后，推断链全部移除。
"""
from types import SimpleNamespace

from services.chapter_history_service import chapter_order_key, list_ordered_chapters


def _node(**kwargs):
    defaults = {
        "id": "n",
        "title": "",
        "extra_data": {},
        "layer": 0,
        "sort_order": 0,
        "position_x": 0,
        "created_at": 0,
        "type": "chapter",
        "work_id": "w",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_chapter_order_key_uses_sort_order():
    assert chapter_order_key(_node(sort_order=3))[0] == 3


def test_chapter_order_key_ignores_title_number():
    """标题文字不再参与排序：改标题不应改变章节顺序。"""
    node = _node(sort_order=1, title="第 12 章 决战")
    assert chapter_order_key(node)[0] == 1


def test_chapter_order_key_ignores_extra_data_number():
    node = _node(sort_order=1, extra_data={"chapter_number": 42})
    assert chapter_order_key(node)[0] == 1


def test_chapter_order_key_breaks_ties_deterministically():
    a = _node(sort_order=1, id="a")
    b = _node(sort_order=1, id="b")
    assert chapter_order_key(a) < chapter_order_key(b)


def test_list_ordered_chapters_sorts_by_sort_order(db_session):
    from models.node import Node
    from models.user import User
    from models.work import CanvasWork

    user = User(username="ord", email="ord@t.t", password_hash="x")
    db_session.add(user)
    db_session.commit()
    work = CanvasWork(user_id=user.id, title="t")
    db_session.add(work)
    db_session.commit()

    # 标题与 sort_order 故意相反，确认排序只认 sort_order
    later = Node(work_id=work.id, type="chapter", title="第 1 章", sort_order=2)
    earlier = Node(work_id=work.id, type="chapter", title="第 2 章", sort_order=1)
    db_session.add_all([later, earlier])
    db_session.commit()

    ordered = list_ordered_chapters(db_session, work.id)
    assert [c.sort_order for c in ordered] == [1, 2]
    assert [c.title for c in ordered] == ["第 2 章", "第 1 章"]
