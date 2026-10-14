"""写作子 Agent：真实工具闭环、上下文隔离和持久化边界。"""
import asyncio
import hashlib
import json

import pytest

from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import SupervisorAgent, get_context, reset_context, set_context
from services.llm.langchain_adapter import DeepAgentChatModel
from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
from services.llm.llm_types import LLMModelConfig


def tools():
    return {tool.name: tool for tool in SupervisorAgent()._get_tools()}


def invoke(name, args):
    return json.loads(asyncio.run(tools()[name].ainvoke(args)))


@pytest.fixture
def writing_context(db_session):
    user = User(username='writer', email='writer@test.local', password_hash='x')
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title='写作隔离')
    db_session.add(work)
    db_session.flush()
    chapter = Node(work_id=work.id, type='chapter', title='第十章',
                   content='王强虽然将动手推到了明后天。\n\n陆沉关上门。', sort_order=10)
    previous = Node(work_id=work.id, type='chapter', title='第九章',
                    content='王强说：“明后天来找我。”\n' + '完整前文' * 1500 + '\nSOURCE_TAIL', sort_order=9)
    note = Node(work_id=work.id, type='note', title='编辑记录', content='EDITOR_NOTE_SECRET', sort_order=0)
    db_session.add_all([chapter, previous, note])
    db_session.flush()
    db_session.add(Chapter(work_id=work.id, node_id=chapter.id, title=chapter.title,
                           content=chapter.content, notes='CHAPTER_NOTE_SECRET：原计划今晚，作者改期。'))
    db_session.commit()
    events = []

    async def emit(event, data):
        events.append((event, data))

    token = set_context({'work_id': work.id, 'user_id': user.id, 'session_id': 'parent-session',
                         'model_pref': {'primary': 'chosen', 'fallback': None}, 'emit': emit,
                         'history': 'PARENT_HISTORY_SECRET', 'last_llm_usage': {'input_tokens': 111}})
    yield chapter, previous, note, events
    reset_context(token)


def task(chapter, previous, operation='revise'):
    return {
        'chapter_node_id': chapter.id,
        'operation': operation,
        'source_node_ids': [previous.id],
        'brief': {
            'scene_plan': '王强当面邀请陆沉明后天同行；陆沉回屋吸收晶核。',
            'narrative_pov': '第三人称限知，当前场景跟随陆沉。',
            'character_knowledge': [{'character': '陆沉', 'known_information': '王强当面说的是明后天。',
                                     'source': '第九章王强的当面对话。'}],
            'story_facts': '陆沉持有三枚晶核；王强真实动机属于世界事实。',
            'prose_requirements': '保留已有文风与完整段落。',
            'revision_scope': '首句改为基于当面听闻的判断，保留其余正文。',
        },
    }


class WriterProvider:
    config = LLMModelConfig(name='chosen', base_url='http://test', api_key='test', provider='openai', model='chosen')
    fallback_config = None

    def __init__(self, submission=None, error=None, before_submit=None):
        self.seen = []
        self.contexts = []
        self.submission = submission or {'replacements': [{'old': '王强虽然将动手推到了明后天。',
                                                         'new': '王强嘴上说的是明后天。'}]}
        self.error = error
        self.before_submit = before_submit

    async def stream_chat(self, messages, **kwargs):
        self.seen.append(messages)
        self.contexts.append(dict(get_context()))
        if self.error:
            raise self.error
        if self.before_submit:
            self.before_submit()
        yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
            tool_name='submit_writing', call_id='writer-submit', arguments=self.submission))


def install_writer(monkeypatch, provider):
    factories = []

    def factory(**kwargs):
        factories.append(kwargs)
        return DeepAgentChatModel(provider=provider, model_name='chosen')

    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', factory)
    return factories


def test_writer_runs_clean_graph_and_saves_exact_replacement(writing_context, db_session, monkeypatch):
    chapter, previous, _, events = writing_context
    provider = WriterProvider()
    factories = install_writer(monkeypatch, provider)
    parent = get_context()
    result = invoke('run_writing_agent', task(chapter, previous))
    assert result['success'] and result['agent'] == 'writer'
    assert factories == [{'primary': 'chosen', 'fallback': None}]
    assert get_context() is parent and parent['last_llm_usage'] == {'input_tokens': 111}
    assert provider.contexts[0].get('history') is None
    assert provider.contexts[0].get('session_id') is None
    messages = provider.seen[0]
    assert [m['role'] for m in messages] == ['system', 'user']
    payload = json.loads(messages[1]['content'])
    assert payload['sources'][0]['content'] == previous.content
    assert 'SOURCE_TAIL' in messages[1]['content']
    assert payload['brief']['character_knowledge'][0]['source'] == '第九章王强的当面对话。'
    for secret in ('PARENT_HISTORY_SECRET', 'EDITOR_NOTE_SECRET', 'CHAPTER_NOTE_SECRET'):
        assert secret not in str(messages)
    db_session.refresh(chapter)
    assert chapter.content == '王强嘴上说的是明后天。\n\n陆沉关上门。'
    persisted = db_session.query(Chapter).filter_by(node_id=chapter.id).one()
    assert persisted.content == chapter.content
    assert 'CHAPTER_NOTE_SECRET' in persisted.notes
    assert any(name == 'chapter_edit_diff' for name, _ in events)
    assert result['content_sha256'] == hashlib.sha256(chapter.content.encode()).hexdigest()


def test_writer_preserves_multiline_replacement_group(writing_context, db_session, monkeypatch):
    chapter, previous, _, events = writing_context
    old = chapter.content
    new = '新增开头。\n\n王强嘴上说的是明后天。\n\n陆沉轻轻关上门。'
    install_writer(monkeypatch, WriterProvider(submission={'replacements': [{'old': old, 'new': new}]}))
    assert invoke('run_writing_agent', task(chapter, previous))['success']
    event = next(data for name, data in events if name == 'chapter_edit_diff')
    assert event['diff']['grouping'] == 'agent_replacements'
    assert len(event['diff']['hunks']) == 1
    assert event['diff']['hunks'][0]['old_text'] == old
    assert event['diff']['hunks'][0]['new_text'] == new
    assert event['node_diff']['hunks'][0]['new_text'] == new


def test_writer_repairs_replacement_without_changing_operation(writing_context, db_session, monkeypatch):
    chapter, previous, _, events = writing_context
    provider = WriterProvider()
    bad = {'replacements': [{'old': '王强虽然将动手推到明后天。', 'new': '王强嘴上说的是明后天。'}]}
    good = provider.submission

    async def stream_chat(messages, **kwargs):
        provider.seen.append(messages)
        submission = bad if len(provider.seen) == 1 else good
        yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
            tool_name='submit_writing', call_id=f'submit-{len(provider.seen)}', arguments=submission))

    provider.stream_chat = stream_chat
    factories = install_writer(monkeypatch, provider)
    result = invoke('run_writing_agent', task(chapter, previous))
    assert result['success']
    assert len(factories) == 1 and len(provider.seen) == 2
    assert json.loads(provider.seen[1][1]['content'])['operation'] == 'revise'
    assert provider.seen[1][-1]['role'] == 'tool'
    assert 'old 在正文中未找到' in provider.seen[1][-1]['content']
    db_session.refresh(chapter)
    assert chapter.content == '王强嘴上说的是明后天。\n\n陆沉关上门。'
    assert sum(name == 'chapter_edit_diff' for name, _ in events) == 1


def test_exhausted_corrections_preserve_body_and_return_original_scope(writing_context, db_session, monkeypatch):
    chapter, previous, _, events = writing_context
    before = chapter.content
    provider = WriterProvider({'replacements': [{'old': '不存在的原文', 'new': '替换文本'}]})
    install_writer(monkeypatch, provider)
    args = task(chapter, previous)
    result = invoke('run_writing_agent', args)
    assert not result['success']
    assert '纠错次数已用尽' in result['error']
    assert result['operation'] == 'revise'
    assert result['revision_scope'] == args['brief']['revision_scope']
    assert len(provider.seen) == 3
    db_session.refresh(chapter)
    assert chapter.content == before
    assert not any(name == 'chapter_edit_diff' for name, _ in events)


def test_writer_receives_writing_method_notes_through_dedicated_input(writing_context, monkeypatch):
    chapter, previous, note, _ = writing_context
    provider = WriterProvider()
    install_writer(monkeypatch, provider)
    args = task(chapter, previous)
    args['writing_note_node_ids'] = [note.id]

    result = invoke('run_writing_agent', args)

    assert result['success']
    payload = json.loads(provider.seen[0][1]['content'])
    assert payload['writing_notes'] == [{
        'node_id': note.id,
        'title': note.title,
        'content': note.content,
    }]
    assert all(source['type'] != 'note' for source in payload['sources'])


def test_writing_note_input_rejects_non_note_nodes(writing_context, monkeypatch):
    chapter, previous, _, _ = writing_context
    args = task(chapter, previous)
    args['writing_note_node_ids'] = [previous.id]
    monkeypatch.setattr(
        'services.agents.llm.get_deep_agent_model',
        lambda **kw: pytest.fail('invalid writing note reached LLM'),
    )

    result = invoke('run_writing_agent', args)

    assert not result['success']


@pytest.mark.parametrize('operation', ['write', 'rewrite', 'humanize'])
def test_writer_supports_full_draft_and_local_humanization(writing_context, db_session, monkeypatch, operation):
    chapter, previous, _, _ = writing_context
    if operation == 'write':
        chapter.content = ''
        db_session.commit()
    submission = ({'content': '陆沉听完，回屋关上门。'} if operation != 'humanize'
                  else {'replacements': [{'old': '陆沉关上门。', 'new': '陆沉反锁了房门。'}]})
    install_writer(monkeypatch, WriterProvider(submission))
    result = invoke('run_writing_agent', task(chapter, previous, operation))
    assert result['success']
    db_session.refresh(chapter)
    assert ('陆沉听完，回屋关上门。' if operation != 'humanize' else '陆沉反锁了房门。') in chapter.content


def test_each_delegation_gets_fresh_context(writing_context, monkeypatch):
    chapter, previous, _, _ = writing_context
    provider = WriterProvider({'content': '独立正文。'})
    install_writer(monkeypatch, provider)
    args = task(chapter, previous, 'rewrite')
    assert invoke('run_writing_agent', args)['success']
    assert invoke('run_writing_agent', args)['success']
    assert len(provider.seen) == 2
    assert all([m['role'] for m in messages] == ['system', 'user'] for messages in provider.seen)


@pytest.mark.parametrize('case', ['notes', 'foreign_source', 'foreign_target', 'write_existing'])
def test_invalid_task_fails_before_model_call(writing_context, db_session, monkeypatch, case):
    chapter, previous, note, _ = writing_context
    args = task(chapter, previous)
    if case == 'notes':
        args['source_node_ids'] = [note.id]
    elif case.startswith('foreign'):
        work = CanvasWork(user_id=get_context()['user_id'], title='另一作品')
        db_session.add(work)
        db_session.flush()
        node = Node(work_id=work.id, type='chapter', title='其他正文', content='FOREIGN', sort_order=1)
        db_session.add(node)
        db_session.commit()
        if case == 'foreign_source':
            args['source_node_ids'] = [node.id]
        else:
            args['chapter_node_id'] = node.id
    else:
        args['operation'] = 'write'
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kw: pytest.fail('invalid input reached LLM'))
    assert not invoke('run_writing_agent', args)['success']


def test_writer_establishes_baseline_from_latest_body_at_start(writing_context, db_session, monkeypatch):
    chapter, previous, _, _ = writing_context
    chapter.content = '用户在委派前刚修改的正文。\n\n陆沉关上门。'
    db_session.commit()
    provider = WriterProvider({'replacements': [{
        'old': '用户在委派前刚修改的正文。',
        'new': '写作代理基于最新正文修改。',
    }]})
    install_writer(monkeypatch, provider)

    result = invoke('run_writing_agent', task(chapter, previous))

    assert result['success']
    db_session.refresh(chapter)
    assert chapter.content.startswith('写作代理基于最新正文修改。')


def test_concurrent_edit_is_preserved(writing_context, db_session, monkeypatch):
    chapter, previous, _, _ = writing_context

    def user_edit():
        chapter.content = 'USER_NEW_BODY'
        db_session.commit()

    install_writer(monkeypatch, WriterProvider(before_submit=user_edit))
    result = invoke('run_writing_agent', task(chapter, previous))
    assert not result['success'] and result['error_code'] == 'content_changed'
    db_session.refresh(chapter)
    assert chapter.content == 'USER_NEW_BODY'


@pytest.mark.parametrize('failure', ['exception', 'missing_submission'])
def test_writer_failure_preserves_body_and_parent_context(writing_context, db_session, monkeypatch, failure):
    chapter, previous, _, _ = writing_context
    before = chapter.content
    parent = get_context()
    error = RuntimeError('writer unavailable')
    provider = WriterProvider(error=error)
    if failure == 'missing_submission':
        async def text_only(*args, **kwargs):
            yield ToolStreamEvent(kind='text', text='尚未完成')
        provider.stream_chat = text_only
    install_writer(monkeypatch, provider)
    result = invoke('run_writing_agent', task(chapter, previous))
    assert not result['success']
    assert get_context() is parent
    db_session.refresh(chapter)
    assert chapter.content == before


def test_cancelling_running_writer_preserves_body(writing_context, db_session, monkeypatch):
    chapter, previous, _, _ = writing_context
    before = chapter.content
    started = asyncio.Event()

    class BlockingProvider(WriterProvider):
        async def stream_chat(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield ToolStreamEvent(kind='text', text='unreachable')

    install_writer(monkeypatch, BlockingProvider())

    async def cancel():
        parent = get_context()
        running = asyncio.create_task(tools()['run_writing_agent'].ainvoke(task(chapter, previous)))
        await asyncio.wait_for(started.wait(), timeout=5)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert get_context() is parent

    asyncio.run(cancel())
    db_session.refresh(chapter)
    assert chapter.content == before


def test_writer_receives_complete_reference_rules(writing_context, monkeypatch):
    from services.agents.tools.writing_agent_tools import REFERENCE_ROOT
    chapter, previous, _, _ = writing_context
    provider = WriterProvider()
    install_writer(monkeypatch, provider)
    assert invoke('run_writing_agent', task(chapter, previous))['success']
    assert (REFERENCE_ROOT / 'chapter_local_edit.txt').read_text() in provider.seen[0][0]['content']


def test_subagent_chunks_do_not_leak_into_supervisor_response(monkeypatch):
    from langchain_core.messages import AIMessage, AIMessageChunk

    class Graph:
        async def astream(self, state, **kwargs):
            yield 'messages', (AIMessageChunk(content='WRITER_INTERNAL', usage_metadata={
                'input_tokens': 999, 'output_tokens': 1, 'total_tokens': 1000}),
                {'langgraph_node': 'model', 'novel_agent_role': 'writer'})
            yield 'updates', {'model': {'messages': [AIMessage(content='已完成。')]}}

    monkeypatch.setattr(SupervisorAgent, '_build_graph', lambda self, **kwargs: Graph())
    emitted = []

    async def emit(event, data):
        emitted.append((event, data))

    result = asyncio.run(SupervisorAgent().run('处理章节', context={}, emit=emit))
    assert result['message'] == '已完成。'
    assert 'WRITER_INTERNAL' not in str(emitted)


def test_parent_graph_delegates_without_forwarding_history(writing_context, monkeypatch):
    from langchain_core.messages import HumanMessage, ToolMessage
    chapter, previous, _, _ = writing_context
    writer = WriterProvider()

    class ParentProvider(WriterProvider):
        async def stream_chat(self, messages, **kwargs):
            if messages[-1]['role'] == 'tool':
                yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                    tool_name='respond_to_user', call_id='finish-1',
                    arguments={'message': '已完成。'}))
                return
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name='run_writing_agent', call_id='delegate-1', arguments=task(chapter, previous)))

    providers = iter([ParentProvider(), writer])
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kw:
                        DeepAgentChatModel(provider=next(providers), model_name='chosen',
                                           profile={'max_input_tokens': 1_000_000}))
    graph = SupervisorAgent()._build_graph(work_id=chapter.work_id)
    result = asyncio.run(graph.ainvoke({'messages': [HumanMessage(content='PARENT_HISTORY_SECRET：把计划往后推。')]}))
    delegation = [m for m in result['messages'] if isinstance(m, ToolMessage) and m.name == 'run_writing_agent']
    assert json.loads(delegation[0].content)['success']
    assert 'PARENT_HISTORY_SECRET' not in str(writer.seen)
    assert json.loads(result['messages'][-1].content)['message'] == '已完成。'


def test_real_supervisor_stream_keeps_writer_output_internal(writing_context, monkeypatch):
    chapter, previous, _, events = writing_context
    args = task(chapter, previous)

    class ParentProvider(WriterProvider):
        async def stream_chat(self, messages, **kwargs):
            if messages[-1]['role'] == 'tool':
                yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                    tool_name='respond_to_user', call_id='finish-stream',
                    arguments={'message': '正式回复。'}))
                yield ToolStreamEvent(kind='usage', usage={'input_tokens': 111, 'output_tokens': 2, 'total_tokens': 113})
                return
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name='run_writing_agent', call_id='delegate-stream', arguments=args))

    class StreamingWriter(WriterProvider):
        async def stream_chat(self, messages, **kwargs):
            yield ToolStreamEvent(kind='text', text='WRITER_INTERNAL_TOKEN')
            async for event in super().stream_chat(messages, **kwargs):
                yield event
            yield ToolStreamEvent(kind='usage', usage={'input_tokens': 999, 'output_tokens': 1, 'total_tokens': 1000})

    providers = iter([ParentProvider(), StreamingWriter()])
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kw:
                        DeepAgentChatModel(provider=next(providers), model_name='chosen',
                                           profile={'max_input_tokens': 1_000_000}))
    result = asyncio.run(SupervisorAgent().run('请修改', context={
        'work_id': chapter.work_id, 'user_id': get_context()['user_id'],
    }, emit=get_context()['emit']))
    assert result['success'] and result['message'] == '正式回复。'
    assert 'WRITER_INTERNAL_TOKEN' not in str(events)
    assert any(event == 'chapter_edit_diff' for event, _ in events)


@pytest.mark.parametrize('submission', [
    {'replacements': [{'old': '不存在的原文', 'new': '替换'}]},
    {'replacements': [{'old': '陆沉关上门。', 'new': '陆沉关上门。'}]},
    {'replacements': [{'old': '。', 'new': '！'}]},
])
def test_invalid_writer_replacements_never_save(writing_context, db_session, monkeypatch, submission):
    chapter, previous, _, _ = writing_context
    before = chapter.content
    install_writer(monkeypatch, WriterProvider(submission))
    assert not invoke('run_writing_agent', task(chapter, previous))['success']
    db_session.refresh(chapter)
    assert chapter.content == before


@pytest.mark.parametrize('mode', ['overwrite', 'replace'])
def test_supervisor_cannot_write_chapter_body_directly(writing_context, db_session, mode):
    chapter, _, _, _ = writing_context
    args = {'node_id': chapter.id, 'mode': mode}
    args.update({'content': '绕过 Writer'} if mode == 'overwrite' else
                {'replacements': [{'old': '陆沉关上门。', 'new': '绕过 Writer'}]})
    assert invoke('update_node', args)['error_code'] == 'writer_required'
    assert invoke('update_node', {'node_id': chapter.id, 'title': '新标题'})['success']
    db_session.refresh(chapter)
    assert '绕过 Writer' not in chapter.content


@pytest.mark.parametrize('batch', [False, True])
def test_supervisor_creates_empty_chapters_and_preserves_nonchapter_writes(writing_context, batch):
    data = {'node_type': 'chapter', 'title': '新章', 'content': '绕过 Writer', 'sort_order': 11}
    name = 'batch_create_nodes' if batch else 'create_node'
    args = lambda: {'nodes_data': [data]} if batch else data
    assert invoke(name, args())['error_code'] == 'writer_required'
    data['content'] = ''
    assert invoke(name, args())['success']
    data.update(node_type='note', content='作者完整要求')
    assert invoke(name, args())['success']


def test_supervisor_cannot_convert_authored_note_into_chapter(writing_context):
    _, _, note, _ = writing_context
    assert invoke('update_node', {'node_id': note.id, 'node_type': 'chapter'})['error_code'] == 'writer_required'


def test_raw_node_editor_remains_available_for_manual_editing(writing_context, db_session):
    from services.agents.tools.node_tools import update_node
    chapter, _, _, _ = writing_context
    result = json.loads(asyncio.run(update_node.ainvoke({'node_id': chapter.id, 'content': '用户编辑正文'})))
    assert result['success']
    db_session.refresh(chapter)
    assert chapter.content == '用户编辑正文'
