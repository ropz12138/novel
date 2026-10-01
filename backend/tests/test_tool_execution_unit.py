"""进行中的工具视为原子：未完成则丢弃该次执行的全部副作用。"""
from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from models.workflow import WorkflowArtifact
from models.session import SupervisorMessage
from services.session_store import session_store
from services.node_content_write_service import write_node_content
from services.tool_execution_unit import ToolExecutionUnit


def _make_user_work(db):
    user = User(username="tool-unit", email="tu@t.t", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    work = CanvasWork(user_id=user.id, title="tu-work")
    db.add(work)
    db.commit()
    db.refresh(work)
    return user, work


def test_rollback_discards_node_chapter_and_artifact_from_in_flight_tool(db_session):
    user, work = _make_user_work(db_session)
    session = session_store.create_session(user_id=user.id, work_id=work.id)
    node = Node(
        sort_order=0,
        work_id=work.id,
        type="chapter",
        title="第五章",
        content="旧正文",
        layer=0,
    )
    db_session.add(node)
    db_session.flush()
    write_node_content(db_session, node, "旧正文")
    db_session.commit()
    db_session.refresh(node)

    unit = ToolExecutionUnit.begin(
        work_id=work.id,
        session_id=session["id"],
        tool_call_id="call_revise",
    )

    node.content = "工具写到一半的新正文"
    write_node_content(db_session, node, "工具写到一半的新正文")
    db_session.add(WorkflowArtifact(
        work_id=work.id,
        chapter_node_id=node.id,
        artifact_type="chapter_draft",
        content="半截草稿",
    ))
    db_session.commit()

    unit.rollback()

    db_session.expire_all()
    restored = db_session.get(Node, node.id)
    assert restored.content == "旧正文"
    chapter = db_session.query(Chapter).filter(Chapter.node_id == node.id).one()
    assert chapter.content == "旧正文"
    assert db_session.query(WorkflowArtifact).filter_by(work_id=work.id).count() == 0


def test_rollback_deletes_chapter_node_created_by_in_flight_tool(db_session):
    user, work = _make_user_work(db_session)
    session = session_store.create_session(user_id=user.id, work_id=work.id)
    plot = Node(sort_order=0, work_id=work.id, type="plot", title="情节", content="", layer=0)
    db_session.add(plot)
    db_session.commit()

    unit = ToolExecutionUnit.begin(
        work_id=work.id,
        session_id=session["id"],
        tool_call_id="call_assemble",
    )
    created = Node(sort_order=1, work_id=work.id, type="chapter", title="新章", content="", layer=0)
    db_session.add(created)
    db_session.commit()

    unit.rollback()

    db_session.expire_all()
    assert db_session.query(Node).filter_by(work_id=work.id, type="chapter").count() == 0
    assert db_session.get(Node, plot.id) is not None


def test_discard_unpaired_tool_calls_keeps_completed_pairs(db_session):
    user, work = _make_user_work(db_session)
    session = session_store.create_session(user_id=user.id, work_id=work.id)
    sid = session["id"]
    session_store.add_message(sid, "user", "改第五章", work_id=work.id)
    session_store.add_message(
        sid, "tool_call", "count_chapter_words",
        meta={"tool_call_id": "c1", "args": {}},
        work_id=work.id,
    )
    session_store.add_message(
        sid, "tool_result", '{"word_count": 100}',
        meta={"tool_call_id": "c1", "tool_name": "count_chapter_words"},
        work_id=work.id,
    )
    session_store.add_message(
        sid, "tool_call", "revise_existing_chapter_draft",
        meta={"tool_call_id": "c2", "args": {}},
        work_id=work.id,
    )

    session_store.discard_unpaired_tool_calls(sid)

    roles = [(m["role"], (m.get("meta") or {}).get("tool_call_id")) for m in session_store.get_messages(sid)]
    assert ("tool_call", "c1") in roles
    assert ("tool_result", "c1") in roles
    assert ("tool_call", "c2") not in roles


def test_rollback_deletes_messages_created_during_in_flight_tool(db_session):
    user, work = _make_user_work(db_session)
    session = session_store.create_session(user_id=user.id, work_id=work.id)
    sid = session["id"]
    session_store.add_message(
        sid, "tool_call", "revise_existing_chapter_draft",
        meta={"tool_call_id": "c2", "args": {}},
        work_id=work.id,
    )
    unit = ToolExecutionUnit.begin(work_id=work.id, session_id=sid, tool_call_id="c2")
    session_store.add_message(
        sid, "assistant", "",
        meta={"type": "chapter_content_diff_card"},
        work_id=work.id,
    )

    unit.rollback()
    session_store.discard_unpaired_tool_calls(sid)

    db_session.expire_all()
    contents = [m["role"] for m in session_store.get_messages(sid)]
    assert "tool_call" not in contents
    assert not any((m.get("meta") or {}).get("type") == "chapter_content_diff_card" for m in session_store.get_messages(sid))
    assert db_session.query(SupervisorMessage).filter_by(session_id=sid).count() == 0
