"""Explicit repair preserves review baselines and current authored content."""
from models.node import Node
from models.work import CanvasWork
from models.user import User
from services import node_agent_diff as diffs


def test_repair_inconsistent_diff_keeps_current_body_and_old_baseline(db_session):
    user = User(username='repair-test', email='repair@test.local', password_hash='x')
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title='修复状态')
    db_session.add(work)
    db_session.flush()
    node = Node(work_id=work.id, type='note', title='笔记', content='旧笔记', sort_order=0)
    db_session.add(node)
    db_session.flush()
    diffs.store_snapshot(db_session, node, '旧笔记', [{'start_offset': 0, 'old_text': '旧笔记', 'new_text': '待审笔记'}])
    node.content = '需求更新后的笔记'
    db_session.commit()
    assert diffs.repair_inconsistent_snapshot(db_session, node) is True
    db_session.flush()
    saved = diffs.get_snapshot(db_session, node)
    assert node.content == '需求更新后的笔记'
    assert saved['original_content'] == '旧笔记'
    assert saved['current_content'] == node.content
    assert diffs.repair_inconsistent_snapshot(db_session, node) is False
    from services.canvas_restore_service import apply_canvas_snapshot
    from schemas.canvas_snapshot import CanvasSnapshot, SnapshotNode
    apply_canvas_snapshot(db_session, work.id, CanvasSnapshot(nodes=[SnapshotNode(
        id=node.id, type='note', title='恢复的笔记', content='待审笔记', sort_order=0)]))
    db_session.refresh(node)
    assert node.content == '待审笔记'
    assert diffs.get_snapshot(db_session, node)['current_content'] == '待审笔记'


def test_edit_resend_restores_checkpoint_after_explicit_diff_repair(db_session):
    import pytest
    from models.session import SupervisorSession, SupervisorMessage
    from services.canvas_checkpoint_service import capture_canvas_checkpoint, prepare_edit_resend
    user = User(username='resend-repair', email='resend@test.local', password_hash='x')
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title='重发修复')
    db_session.add(work)
    db_session.flush()
    session = SupervisorSession(user_id=user.id, work_id=work.id)
    node = Node(work_id=work.id, type='note', title='笔记', content='已修改的完整笔记', sort_order=0)
    db_session.add_all([session, node])
    db_session.flush()
    diffs.store_snapshot(db_session, node, '原始笔记', [{'start_offset': 0, 'old_text': '原始笔记', 'new_text': node.content}])
    message = SupervisorMessage(session_id=session.id, work_id=work.id, role='user', content='设计第三章', sort_order=0)
    db_session.add(message)
    db_session.flush()
    capture_canvas_checkpoint(db_session, session_id=session.id, work_id=work.id,
                              trigger_message_id=message.id, sort_order=0)
    message_id, session_id, work_id, node_id = message.id, session.id, work.id, node.id
    node.content = '需求更新后的短笔记'
    db_session.commit()
    with pytest.raises(ValueError, match='工具分组状态与当前正文不一致'):
        prepare_edit_resend(db_session, session_id=session_id, work_id=work_id,
                            message_id=message_id, new_content='修改后的请求')
    db_session.rollback()
    node = db_session.get(Node, node_id)
    assert node.content == '需求更新后的短笔记'
    assert diffs.repair_inconsistent_snapshot(db_session, node)
    db_session.commit()
    result = prepare_edit_resend(db_session, session_id=session_id, work_id=work_id,
                                 message_id=message_id, new_content='修改后的请求')
    assert result['content'] == '修改后的请求'
    db_session.refresh(node)
    assert node.content == '已修改的完整笔记'
    assert diffs.get_snapshot(db_session, node)['current_content'] == node.content
