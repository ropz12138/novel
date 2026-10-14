import asyncio
import hashlib
import json

import pytest

from models.chapter import Chapter
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork
from schemas.node import NodeResponse
from services.agents.supervisor import set_context
from services.agents.tools import workflow_skill_tools as tools
from services.node_content_write_service import write_node_content
from routers.node import update_node as update_node_route
from schemas.node import NodeUpdate


@pytest.fixture
def chapters(db_session):
    user = User(username='notes', email='notes@test.local', password_hash='x')
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title='笔记测试')
    db_session.add(work)
    db_session.flush()
    nodes = [Node(work_id=work.id, type='chapter', title=f'第{i}章', sort_order=i,
                  content=f'正文{i}：晶核数量{i}。') for i in range(1, 5)]
    outline = Node(work_id=work.id, type='outline', title='大纲', sort_order=0)
    volume = Node(work_id=work.id, type='volume', title='第一卷', sort_order=0)
    plot = Node(work_id=work.id, type='plot', title='主线', sort_order=0)
    db_session.add_all([outline, volume, plot, *nodes])
    db_session.flush()
    db_session.add_all([
        Edge(work_id=work.id, source_id=outline.id, target_id=volume.id),
        Edge(work_id=work.id, source_id=volume.id, target_id=plot.id),
        *[Edge(work_id=work.id, source_id=plot.id, target_id=node.id) for node in nodes],
    ])
    db_session.commit()
    set_context({'work_id': work.id, 'session_id': 'new-session'})
    yield nodes
    set_context({})


def invoke(name, **kwargs):
    return json.loads(asyncio.run(getattr(tools, name).ainvoke(kwargs)))


def test_notes_exposed_to_frontend_and_preserved_after_body_edit(chapters, db_session):
    node = chapters[0]
    db_session.add(Chapter(work_id=node.work_id, node_id=node.id, summary='摘要：得到晶核。\n作者要求：保留伤势。\n设计：后续偿还。'))
    db_session.commit()
    db_session.expire_all()
    assert '作者要求' in NodeResponse.model_validate(node).notes
    write_node_content(db_session, node, '改后正文')
    db_session.commit()
    assert '作者要求' in db_session.query(Chapter).filter_by(node_id=node.id).one().notes


def test_manual_node_update_can_edit_chapter_notes(chapters, db_session):
    node = chapters[0]
    user = db_session.query(User).one()

    response = update_node_route(
        node.id,
        NodeUpdate(notes='## 连续性\n\n- 保留伤势'),
        db_session,
        user,
    )

    assert response.notes == '## 连续性\n\n- 保留伤势'
    assert db_session.query(Chapter).filter_by(node_id=node.id).one().notes == response.notes


def test_context_reads_all_preceding_full_text_and_notes_in_new_session(chapters, db_session):
    first = chapters[0]
    notes = '作者要求及设计。' * 1000
    db_session.add(Chapter(work_id=first.work_id, node_id=first.id, summary=notes))
    db_session.commit()
    catalog = invoke('list_chapters')
    result = invoke('read_chapter_context', chapter_numbers=[1, 2, 3], catalog_revision=catalog['catalog_revision'])
    note_result = invoke('read_chapter_notes', chapter_numbers=[1, 2], catalog_revision=catalog['catalog_revision'])
    assert result['success'], result
    assert [n['chapter_node_id'] for n in result['chapters']] == [n.id for n in chapters[:3]]
    assert note_result['chapters'][0]['notes'] == notes
    assert result['chapters'][1]['content'] == chapters[1].content
    set_context({'work_id': 'other'})
    assert not invoke('read_chapter_context', chapter_numbers=[3], catalog_revision=catalog['catalog_revision'])['success']


def test_notes_can_be_saved_and_reject_stale_body(chapters, db_session):
    node = chapters[0]
    digest = hashlib.sha256(node.content.encode()).hexdigest()
    result = invoke('save_chapter_notes', chapter_node_id=node.id,
                    notes='摘要、作者要求、设计、连续性事实', expected_content_sha256=digest)
    assert result['success']
    assert db_session.query(Chapter).filter_by(node_id=node.id).one().notes == '摘要、作者要求、设计、连续性事实'
    assert not invoke('save_chapter_notes', chapter_node_id=node.id, notes='过时笔记',
                      expected_content_sha256='old')['success']


def test_cancelled_tool_restores_notes_with_body(chapters, db_session):
    from services.tool_execution_unit import ToolExecutionUnit
    node = chapters[0]
    db_session.add(Chapter(work_id=node.work_id, node_id=node.id, notes='原作者要求'))
    db_session.commit()
    unit = ToolExecutionUnit.begin(work_id=node.work_id, session_id=None, tool_call_id='notes-change')
    invoke('save_chapter_notes', chapter_node_id=node.id, notes='新作者要求',
           expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest())
    unit.rollback()
    db_session.expire_all()
    assert db_session.query(Chapter).filter_by(node_id=node.id).one().notes == '原作者要求'


def test_saved_notes_emit_refresh_and_are_returned_by_node_list(chapters, db_session):
    from routers.node import list_nodes
    node = chapters[0]
    events = []

    async def emit(name, data):
        events.append((name, data))

    set_context({'work_id': node.work_id, 'emit': emit})
    notes = '事实摘要：获得晶核。\n作者要求：数量逐项核对。\n创作设计：暂存。'
    invoke('save_chapter_notes', chapter_node_id=node.id, notes=notes,
           expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest())
    db_session.expire_all()
    response = list_nodes(node.work_id, db_session, db_session.query(User).one())
    assert next(n for n in response.nodes if n.id == node.id).notes == notes
    assert events[-1] == ('nodes_updated', {'action': 'chapter_notes', 'chapter_node_id': node.id,
                                           'content_changed': False})
    assert events[0][0] == 'chapter_notes_diff'
    assert events[0][1]['current_notes'] == notes


@pytest.mark.parametrize('notes', ['', '  ', None])
def test_memory_rejects_empty_notes(notes):
    with pytest.raises(ValueError):
        tools.SaveChapterNotesInput(notes=notes, chapter_node_id='chapter',
                                    expected_content_sha256='hash')
