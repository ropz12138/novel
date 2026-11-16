"""连续分镜工具：真实项目模型基类、完整上下文与多批执行。"""
import asyncio
import copy
import json
import pytest
from langchain_core.messages import AIMessage
from schemas.short_drama import StoryboardChatRequest
from services.agents import storyboard_agent as agent
from services.storyboard_tools import apply_operation
from services.agents.supervisor import get_context, reset_context, set_context

CHAPTER = {'id': 'chapter-1', 'title': '雨夜', 'content': '林雨推开门。\n\n陈舟看着信封。'}
ROLES = [{'id': 'role-1', 'title': '林雨', 'content': '黑色长发，蓝色棉布上衣。'}]
NAMES = ['get_storyboard', 'replace_storyboard', 'insert_shots', 'update_shots', 'delete_shots', 'reorder_shots', 'get_portraits', 'insert_portraits', 'update_portraits', 'delete_portraits', 'finish_turn']

def shot(id='shot-1', prompt='原有镜头'):
    return dict(id=id, title='推门', prompt=prompt, duration=5, seed=777, mode='base', inputMode='reference', roles=[dict(roleId='role-1', portraitId=None)], sourceQuote='林雨推开门。', sourceStartLine=None, sourceEndLine=None, referencePaths='refs/lin.png', firstFrame='', lastFrame='', firstFrameShotId='')

def designed(id=None):
    return dict(id=id, title='推门中景', prompt='完整中文视频提示词', duration=5, roles=[dict(roleId='role-1', portraitId=None)], firstFrameShotId=None)

def request(**kwargs):
    return StoryboardChatRequest.model_validate(dict(message='设计这一章的分镜', source_content=CHAPTER['content'], session_id='session-1', **kwargs))

class MemoryRepository:
    def __init__(self, shots=(), chapter=CHAPTER):
        self.board = dict(shots=copy.deepcopy(list(shots)), revision=0, portraitRevision=0, width=960, height=544, style='', portraits=[], sourceContent=chapter['content'], activeSessionId='session-1')
        self.source = chapter['content']
    def read(self):
        return copy.deepcopy(self.board)
    def mutate(self, operation, payload):
        assert self.board['revision'] == payload['expected_revision']
        shots, changes = apply_operation(operation, payload, self.board['shots'], self.source, {'role-1'}, self.board['portraits'])
        self.board.update(shots=shots, revision=self.board['revision'] + 1)
        return self.read(), changes
    def mutate_portraits(self, operation, payload):
        from services.portrait_tools import apply_portrait_operation
        assert self.board['portraitRevision'] == payload['expected_revision']
        portraits, changes = apply_portrait_operation(operation, payload, self.board['portraits'], {'role-1'})
        self.board.update(portraits=portraits, portraitRevision=self.board['portraitRevision'] + 1)
        return self.read(), changes

def run(monkeypatch, actions, *, req=None, chapter=CHAPTER):
    req = req or request()
    repository = MemoryRepository([s.model_dump() for s in req.shots], chapter)
    seen = []
    async def runtime(**kwargs):
        seen.append({**kwargs, 'context': copy.deepcopy(get_context())})
        tools = {t.name: t for t in kwargs['tools']}
        for name, payload in actions:
            await tools[name].ainvoke(payload)
    monkeypatch.setattr(agent, 'invoke_isolated_subagent', runtime)
    result = asyncio.run(agent.design_storyboard(chapter=chapter, roles=ROLES, request=req, user_id='u', work_id='w', model_pref={'primary': 'chosen', 'fallback': ''}, repository=repository))
    return result, seen


def test_full_context_skill_and_model_preferences_are_isolated(monkeypatch):
    chapter = dict(CHAPTER, content=CHAPTER['content'] + '\n' + '全文保留' * 20000)
    history = '完整历史要求' * 10000
    token = set_context({'user_id': 'other', 'history': 'Supervisor 私有历史'})
    try:
        result, seen = run(monkeypatch, [('finish_turn', {'message': '讨论'})], chapter=chapter,
            req=request(history=[{'role': 'user', 'content': history}]))
        assert get_context()['user_id'] == 'other'
    finally:
        reset_context(token)
    captured = seen[0]
    from services.storyboard_source import numbered_source
    assert captured['task']['chapter']['content'] == numbered_source(chapter['content'])
    assert captured['task']['chapter']['line_count'] == len(chapter['content'].split('\n'))
    assert captured['task']['conversation'][0]['content'] == history
    assert captured['context']['model_pref']['primary'] == 'chosen'
    assert 'Supervisor 私有历史' not in json.dumps(captured['task'], ensure_ascii=False)
    assert [t.name for t in captured['tools']] == NAMES
    assert captured['completion_tool_name'] == 'finish_turn'
    for path in (agent.PROMPT_PATH, agent.SKILL_PATH, agent.H3_GUIDE_PATH):
        assert path.read_text() in captured['system_prompt']
    assert result['shots'] is None


def test_two_batches_finish_after_both_and_preserve_other_fields(monkeypatch):
    first, second = shot(), shot('shot-2')
    result, _ = run(monkeypatch, [
        ('update_shots', {'expected_revision': 0, 'updates': [{'id': 'shot-1', 'prompt': '中文一'}]}),
        ('update_shots', {'expected_revision': 1, 'updates': [{'id': 'shot-2', 'prompt': '中文二'}]}),
        ('finish_turn', {'message': '两个镜头已改成中文'})], req=request(shots=[first, second]))
    assert result['shots'] == [dict(first, prompt='中文一'), dict(second, prompt='中文二')]
    assert len(result['changes']) == 2


def test_missing_finish_is_error_even_after_successful_write(monkeypatch):
    with pytest.raises(RuntimeError, match='最终回复'):
        run(monkeypatch, [('replace_storyboard', {'expected_revision': 0, 'shots': [designed()]})])


def test_no_hard_total_duration_or_shot_limit(monkeypatch):
    result, seen = run(monkeypatch, [('replace_storyboard', {'expected_revision': 0, 'shots': [designed() for _ in range(43)]}), ('finish_turn', {'message': '完成'})])
    assert len(result['shots']) == 43
    assert sum(s['duration'] for s in result['shots']) == 215
    assert 'target_duration_seconds' not in seen[0]['task']['settings']


def test_read_returns_full_prompt_and_current_version(monkeypatch):
    full = '完整提示词' * 20000
    repository = MemoryRepository([shot(prompt=full)])
    async def runtime(**kwargs):
        tools = {t.name: t for t in kwargs['tools']}
        data = json.loads(await tools['get_storyboard'].ainvoke({'shot_ids': ['shot-1']}))
        assert data['shots'][0]['prompt'] == full and data['revision'] == 0
        assert data['shot_count'] == 1 and data['total_duration'] == 5
        await tools['finish_turn'].ainvoke({'message': '读取完成'})
    monkeypatch.setattr(agent, 'invoke_isolated_subagent', runtime)
    asyncio.run(agent.design_storyboard(chapter=CHAPTER, roles=ROLES, request=request(), user_id='u', work_id='w', model_pref={}, repository=repository))


@pytest.mark.parametrize('changes', [{'seed': 9}, {'prompt': None}, {'prompt': ''}, {}])
def test_update_schema_rejects_media_fields_null_and_empty_patch(changes):
    from pydantic import ValidationError
    from schemas.short_drama import UpdateShots
    with pytest.raises(ValidationError):
        UpdateShots.model_validate({'expected_revision': 0, 'updates': [{'id': 'shot-1', **changes}]})


def test_real_project_adapter_streams_batches_and_finish(monkeypatch):
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    class Provider:
        calls = 0
        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                name, args = 'update_shots', {'expected_revision': 0, 'updates': [{'id': 'shot-1', 'prompt': '中文一'}]}
            elif self.calls == 2:
                name, args = 'update_shots', {'expected_revision': 1, 'updates': [{'id': 'shot-2', 'prompt': '中文二'}]}
                assert 'saved' in str(messages)
            else:
                name, args = 'finish_turn', {'message': '两个镜头全部完成'}
            yield ToolStreamEvent(kind='thinking', text='完整思考')
            raw = json.dumps(args, ensure_ascii=False)
            yield ToolStreamEvent(kind='tool_call_delta', text=raw, index=0, tool_call=ToolCallFinished(name, str(self.calls), {}))
            yield ToolStreamEvent(kind='tool_call', index=0, tool_call=ToolCallFinished(name, str(self.calls), args))
    provider = Provider()
    def factory(**kwargs):
        assert kwargs == {'primary': 'chosen', 'fallback': ''}
        return DeepAgentChatModel(provider=provider, model_name='chosen')
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', factory)
    events = []
    async def emit(event, data): events.append((event, data))
    repository = MemoryRepository([shot(), shot('shot-2')])
    result = asyncio.run(agent.design_storyboard(chapter=CHAPTER, roles=ROLES, request=request(), user_id='u', work_id='w', model_pref={'primary': 'chosen', 'fallback': ''}, repository=repository, emit=emit))
    assert provider.calls == 3 and result['message'] == '两个镜头全部完成'
    assert [s['prompt'] for s in result['shots']] == ['中文一', '中文二']
    assert [d['workspace']['revision'] for e,d in events if e == 'storyboard_updated'] == [1, 2]
    assert len([e for e,d in events if e == 'tool_end']) == 3
    assert len([e for e,d in events if e == 'storyboard_stream' and d['phase'] == 'reasoning']) == 3


def test_prompt_positive_only():
    text = agent.PROMPT_PATH.read_text()
    assert all(term not in text for term in ('禁止', '不要', '不得', '不能', '不允许'))


def test_continuing_runtime_returns_precise_errors_and_retries_same_batch(monkeypatch):
    from services.agents import llm
    responses = [
        AIMessage(content='', tool_calls=[dict(name='update_shots', id='bad', args=dict(expected_revision=0, updates=[
            dict(id='shot-1', title=' '), dict(id='shot-2', title=' ')]))]),
        AIMessage(content='', tool_calls=[dict(name='update_shots', id='fixed', args=dict(expected_revision=0, updates=[
            dict(id='shot-1', prompt='中文一'), dict(id='shot-2', prompt='中文二')]))]),
        AIMessage(content='', tool_calls=[dict(name='finish_turn', id='finish', args=dict(message='两个镜头已完成'))]),
    ]
    seen = []
    class Model:
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages, **kwargs):
            seen.append(list(messages))
            return responses.pop(0)
    monkeypatch.setattr(llm, 'get_deep_agent_model', lambda **kwargs: Model())
    repository = MemoryRepository([shot(), shot('shot-2')])
    result = asyncio.run(agent.design_storyboard(chapter=CHAPTER, roles=ROLES, request=request(), user_id='u', work_id='w', model_pref={}, repository=repository))
    feedback = json.loads(seen[1][-1].content)
    assert [e['shot_id'] for e in feedback['errors']] == ['shot-1', 'shot-2']
    assert feedback['written'] is False
    assert repository.board['revision'] == 1
    assert [s['prompt'] for s in result['shots']] == ['中文一', '中文二']
    assert len(result['changes']) == 1
