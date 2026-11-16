"""分镜的行号引用与按模型调用持久化的有序时间线。"""
import asyncio
import json
import pytest
from sqlalchemy import inspect
from tests.test_short_drama_api import drama, call, parse_sse
from tests.test_short_drama_persistence import api
from schemas.short_drama import ReplaceStoryboard
from services.storyboard_tools import apply_operation, StoryboardToolError


def test_line_reference_extracts_original_and_never_requires_copying_quotes():
    source = '第一行。\n\n第三行。\r\n最后一行。\n'
    payload = dict(expected_revision=0, shots=[
        dict(title='镜头', prompt='完整提示词', duration=5, sourceStartLine=3, sourceEndLine=4)])
    shots, _ = apply_operation('replace_storyboard', payload, [], source, set())
    assert shots[0]['sourceQuote'] == '第三行。\r\n最后一行。'
    assert (shots[0]['sourceStartLine'], shots[0]['sourceEndLine']) == (3, 4)
    assert 'sourceQuote' not in ReplaceStoryboard.model_json_schema()['$defs']['DesignedShot']['properties']
    with pytest.raises(StoryboardToolError, match='invalid_source_lines'):
        apply_operation('replace_storyboard', dict(shots=[dict(title='坏范围', prompt='提示词', duration=5,
            sourceStartLine=8, sourceEndLine=9)]), [], source, set())


def test_every_llm_call_and_tool_result_survives_reload_in_order(drama, monkeypatch, db_session):
    from routers import short_drama
    session = api(drama, 'POST', '/sessions', {'title': '完整过程'}).json()
    long_text = '完整思考与提示词' * 12000
    async def fake(**kwargs):
        emit = kwargs['emit']
        await emit('stage_start', {'label': '第一轮'})
        await emit('storyboard_stream', {'phase': 'reasoning', 'chunk': '第一次思考'})
        await emit('storyboard_stream', {'phase': 'content', 'chunk': '第一次说明'})
        await emit('storyboard_stream', {'phase': 'tool_args', 'tool': 'replace_storyboard', 'tool_call_id': 'bad', 'tool_index': 0,
            'chunk': '{"expected_revision":0,"shots":[]}'})
        await emit('llm_end', {})
        await emit('tool_start', {'tool': 'replace_storyboard', 'tool_call_id': 'bad', 'tool_index': 0, 'arguments': {'expected_revision': 0, 'shots': []}})
        await emit('tool_error', {'tool': 'replace_storyboard', 'tool_call_id': 'bad', 'detail': '行号超出章节范围'})
        first = api(drama, 'GET', '/sessions/' + session['id']).json()['messages']
        assert [m['role'] for m in first] == ['user', 'assistant', 'tool_call', 'tool_result']
        assert first[1]['reasoning'] == '第一次思考'
        assert first[2]['status'] == 'failed' and first[3]['content'] == '行号超出章节范围'
        await emit('stage_start', {'label': '第二轮'})
        await emit('storyboard_stream', {'phase': 'reasoning', 'chunk': long_text})
        await emit('storyboard_stream', {'phase': 'content', 'chunk': '第二次说明'})
        args = {'expected_revision': 0, 'shots': [{'title': '修正镜头', 'prompt': long_text, 'duration': 5, 'sourceStartLine': 1, 'sourceEndLine': 1}]}
        raw = json.dumps(args, ensure_ascii=False)
        await emit('storyboard_stream', {'phase': 'tool_args', 'tool': 'replace_storyboard', 'tool_call_id': 'good', 'tool_index': 0, 'chunk': raw})
        await emit('llm_end', {})
        await emit('tool_start', {'tool': 'replace_storyboard', 'tool_call_id': 'good', 'tool_index': 0, 'arguments': args})
        board, _ = kwargs['repository'].mutate('replace_storyboard', args)
        await emit('tool_end', {'tool': 'replace_storyboard', 'tool_call_id': 'good', 'result': {'success': True, 'saved': True, 'shots': board['shots']}})
        await emit('stage_start', {'label': '第三轮'})
        await emit('storyboard_stream', {'phase': 'reasoning', 'chunk': '第三次思考'})
        await emit('llm_end', {})
        return {'message': '全部完成', 'shots': board['shots']}
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    result = api(drama, 'POST', '/chat', {'session_id': session['id'], 'message': '设计分镜', 'source_content': drama[3].content})
    events = parse_sse(result.text)
    assert events[-1][0] == 'storyboard_done'
    rows = api(drama, 'GET', '/sessions/' + session['id']).json()['messages']
    assistants = [m for m in rows if m['role'] == 'assistant']
    assert [m['reasoning'] for m in assistants] == ['第一次思考', long_text, '第三次思考']
    assert [m['content'] for m in assistants] == ['第一次说明', '第二次说明', '全部完成']
    calls = [m for m in rows if m['role'] == 'tool_call']
    assert [m['tool_call_id'] for m in calls] == ['bad', 'good']
    assert calls[1]['arguments'] == json.dumps(args := {'expected_revision': 0, 'shots': [{'title': '修正镜头', 'prompt': long_text, 'duration': 5, 'sourceStartLine': 1, 'sourceEndLine': 1}]}, ensure_ascii=False)
    assert [m['role'] for m in rows if m['role'] != 'process'] == ['user', 'assistant', 'tool_call', 'tool_result', 'assistant', 'tool_call', 'tool_result', 'assistant']
    assert len({m['id'] for m in rows}) == len(rows)
    assert any(e == 'message_updated' for e, d in events)
    assert all(c['type'].__class__.__name__ not in ('JSON', 'JSONB') for c in inspect(db_session.bind).get_columns('drama_messages'))


def test_real_model_runtime_persists_correction_rounds_and_numbered_source(drama, monkeypatch):
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    class Provider:
        calls = 0
        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            assert '1 | 林雨推开门。' in str(messages)
            if self.calls == 2:
                assert 'empty_text' in str(messages)
            if self.calls < 3:
                name = 'replace_storyboard'
                args = dict(expected_revision=0, shots=[dict(title=' ' if self.calls == 1 else '镜头', prompt='完整视频提示词', duration=5, firstFrameShotId=None)])
            else:
                name, args = 'finish_turn', {'message': '分镜已生成'}
            yield ToolStreamEvent(kind='thinking', text=f'第{self.calls}轮思考')
            if self.calls < 3:
                yield ToolStreamEvent(kind='text', text=f'第{self.calls}轮说明')
            raw = json.dumps(args, ensure_ascii=False)
            for fragment in (raw[:12], raw[12:]):
                yield ToolStreamEvent(kind='tool_call_delta', text=fragment, index=0,
                    tool_call=ToolCallFinished(name, f'call{self.calls}', {}))
            yield ToolStreamEvent(kind='tool_call', index=0, tool_call=ToolCallFinished(name, f'call{self.calls}', args))
    provider = Provider()
    monkeypatch.setattr('services.agents.subagent_runtime.llm.get_deep_agent_model',
        lambda **kwargs: DeepAgentChatModel(provider=provider, model_name='chosen'))
    events = parse_sse(call(drama).text)
    assert events[-1][0] == 'storyboard_done', events[-1]
    assert provider.calls == 3
    rows = events[-1][1]['messages']
    assert [r['reasoning'] for r in rows if r['role'] == 'assistant'] == ['第1轮思考', '第2轮思考', '第3轮思考']
    tools = [r for r in rows if r['role'] == 'tool_call']
    assert [r['status'] for r in tools] == ['failed', 'done', 'done']
    assert len([r for r in rows if r['role'] == 'tool_result']) == 3
    assert 'empty_text' in next(r['content'] for r in rows if r['role'] == 'tool_result')
    assistants = {r['id'] for r in rows if r['role'] == 'assistant'}
    assert all(r['llm_call_id'] in assistants for r in tools)
    assert events[-1][1]['workspace']['shots'][0]['sourceQuote'] == ''


def test_interrupted_llm_preserves_partial_thought_and_tool_arguments(drama, monkeypatch):
    from routers import short_drama
    async def fake(**kwargs):
        await kwargs['emit']('stage_start', {'label': '设计'})
        await kwargs['emit']('storyboard_stream', {'phase': 'reasoning', 'chunk': '已产生的完整思考'})
        await kwargs['emit']('storyboard_stream', {'phase': 'tool_args', 'tool': 'replace_storyboard', 'tool_call_id': 'partial', 'chunk': '{"shots":[{"prompt":"尚未结束'})
        raise RuntimeError('模型链路中断')
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    events = parse_sse(call(drama).text)
    assert events[-1] == ('error', {'message': '模型链路中断'})
    sessions = api(drama, 'GET', '/sessions').json()
    rows = api(drama, 'GET', '/sessions/' + sessions[0]['id']).json()['messages']
    assert rows[1]['reasoning'] == '已产生的完整思考'
    assert rows[2]['arguments'] == '{"shots":[{"prompt":"尚未结束'
    assert rows[2]['status'] == 'failed'
    assert rows[-1]['role'] == 'error' and rows[-1]['content'] == '模型链路中断'


def test_upgrade_preserves_existing_shots_messages_and_backfills_lines(drama, db_session):
    from models.short_drama import DramaShot, DramaWorkspace, DramaMessage
    from services.short_drama_migration import upgrade_storyboard_records
    from sqlalchemy import text
    session = api(drama, 'POST', '/sessions', {'title': '迁移'}).json()
    api(drama, 'GET')
    workspace = db_session.query(DramaWorkspace).one()
    workspace.source_content = '第一行\n\n第二段\n末行'
    row = DramaShot(workspace_id=workspace.id, shot_id='legacy', sort_order=0, source_quote='第二段\n末行')
    message = DramaMessage(session_id=session['id'], role='assistant', content='旧的完整回复', reasoning='旧思考', sort_order=0)
    db_session.add_all([row, message]); db_session.commit()
    # Recreate the actual pre-upgrade column layout without touching production.
    for table, columns in {'drama_messages': ['turn_id','llm_call_id','tool_call_id','tool_name','arguments','status'],
                           'drama_shots': ['source_start_line','source_end_line']}.items():
        for column in columns:
            db_session.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
    db_session.commit()
    upgrade_storyboard_records(db_session.bind)
    upgrade_storyboard_records(db_session.bind)
    db_session.expire_all()
    shot = db_session.query(DramaShot).one()
    assert (shot.source_start_line, shot.source_end_line) == (3, 4)
    assert shot.source_quote == '第二段\n末行'
    old = db_session.query(DramaMessage).one()
    assert old.content == '旧的完整回复' and old.reasoning == '旧思考' and old.status == 'done'


def test_restart_closes_persisted_running_messages(drama, db_session):
    from models.short_drama import DramaSession, DramaMessage
    from services.short_drama_store import recover_interrupted
    session = api(drama, 'POST', '/sessions', {'title': '重启恢复'}).json()
    db_session.get(DramaSession, session['id']).running = True
    row = DramaMessage(session_id=session['id'], role='assistant', content='', reasoning='重启前思考', sort_order=0, status='running')
    db_session.add(row); db_session.commit()
    recover_interrupted(db_session)
    db_session.expire_all()
    assert db_session.get(DramaMessage, row.id).status == 'failed'
    assert db_session.get(DramaMessage, row.id).reasoning == '重启前思考'


def test_invalid_json_tool_arguments_are_saved_as_failed_before_next_round(drama, monkeypatch):
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    class Provider:
        calls = 0
        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ToolStreamEvent(kind='thinking', text='第一轮思考')
                yield ToolStreamEvent(kind='tool_call_delta', text='{"shots":[broken', index=0,
                    tool_call=ToolCallFinished('replace_storyboard', 'broken', {}))
            else:
                raw = json.dumps({'message': '已说明错误'})
                yield ToolStreamEvent(kind='tool_call_delta', text=raw, index=0,
                    tool_call=ToolCallFinished('finish_turn', 'finish', {}))
    provider = Provider()
    monkeypatch.setattr('services.agents.subagent_runtime.llm.get_deep_agent_model',
        lambda **kwargs: DeepAgentChatModel(provider=provider, model_name='chosen'))
    events = parse_sse(call(drama).text)
    assert events[-1][0] == 'storyboard_done', events[-1]
    rows = events[-1][1]['messages']
    bad = next(row for row in rows if row['role'] == 'tool_call' and row['tool_call_id'] == 'broken')
    assert bad['arguments'] == '{"shots":[broken'
    assert bad['status'] == 'failed'
    assert any(row['role'] == 'tool_result' and row['tool_call_id'] == 'broken' for row in rows)
