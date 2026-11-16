import asyncio
import json

from fastapi.testclient import TestClient
import pytest
from main import app
from models.user import User
from models.work import CanvasWork
from models.node import Node
from services.auth_service import auth_service
from routers import short_drama

client = TestClient(app)


@pytest.fixture
def drama(db_session):
    user = User(username='drama', email='drama@test.local', password_hash='x', primary_model='chosen', fallback_model='')
    other = User(username='other', email='other-drama@test.local', password_hash='x')
    db_session.add_all([user, other]); db_session.flush()
    work = CanvasWork(user_id=user.id, title='雨夜')
    db_session.add(work); db_session.flush()
    chapter = Node(work_id=work.id, type='chapter', title='第一章', content='林雨推开门。', sort_order=1)
    role = Node(work_id=work.id, type='character', title='林雨', content='角色完整设定', sort_order=2)
    db_session.add_all([chapter, role]); db_session.commit()
    return user, other, work, chapter, role


def parse_sse(text):
    events = []
    name = None
    data = []
    for line in text.splitlines():
        if line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            data.append(line[6:])
        elif line == '' and name is not None:
            events.append((name, json.loads('\n'.join(data))))
            name = None
            data = []
    return events


def call(drama, *, user=None, chapter=None, **changes):
    owner, _, work, source, _ = drama
    root = f'/api/works/{work.id}/short-drama'
    token = {'Authorization': 'Bearer ' + auth_service.create_access_token(owner.id)}
    sessions = client.get(root + '/sessions', headers=token).json()
    session = sessions[0] if sessions else client.post(root + '/sessions', json={'title': '测试'}, headers=token).json()
    body = dict(message='帮我设计分镜', source_content=source.content, session_id=session['id'])
    body.update(changes)
    return client.post(f'/api/works/{work.id}/chapters/{(chapter or source).id}/short-drama/chat', json=body, headers={'Authorization': 'Bearer ' + auth_service.create_access_token((user or owner).id)})


def test_login_required():
    response = client.post('/api/works/w/chapters/c/short-drama/chat', json={'message':'设计', 'source_content':'正文', 'session_id':'s'})
    assert response.status_code == 401


def test_owner_check_and_chapter_type_before_any_model_call(drama, monkeypatch):
    async def fail(**kwargs):
        pytest.fail('unauthorized request invoked model')
    monkeypatch.setattr(short_drama, 'design_storyboard', fail)
    assert call(drama, user=drama[1]).status_code == 404
    assert call(drama, chapter=drama[4]).status_code == 400


def test_endpoint_loads_authoritative_chapter_roles_and_user_model_pref(drama, monkeypatch):
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs)
        await kwargs['emit']('stage_start', {'label': '正在设计分镜'})
        await kwargs['emit']('storyboard_stream', {'phase': 'reasoning', 'chunk': '先看全文。'})
        await kwargs['emit']('storyboard_stream', {'phase': 'tool_args', 'tool': 'finish_turn', 'tool_call_id': 'finish', 'chunk': '{"message":"先确认目标时长。"'})
        return {'message': '先确认目标时长。', 'shots': None}
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    response = call(drama)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['x-accel-buffering'] == 'no'
    events = parse_sse(response.text)
    deltas = [data for event, data in events if event == 'storyboard_stream']
    assert deltas[0]['phase'] == 'reasoning' and deltas[0]['chunk'] == '先看全文。'
    assert deltas[1]['phase'] == 'tool_args'
    assert events[-1][0] == 'storyboard_done'
    assert events[-1][1]['message'] == '先确认目标时长。'
    assert events[-1][1]['shots'] is None
    assert all(data.get('label') != '正在保存本轮对话' for _, data in events)
    assert all(row['content'] != '正在保存本轮对话' for row in events[-1][1]['messages'])
    assert seen[0]['chapter']['content'] == drama[3].content
    assert seen[0]['roles'][0]['content'] == '角色完整设定'
    assert seen[0]['model_pref'] == {'primary': 'chosen', 'fallback': ''}
    assert drama[3].content == '林雨推开门。'


def test_stream_heartbeats_while_the_model_is_silent_between_deltas(drama, monkeypatch):
    monkeypatch.setattr(short_drama, 'HEARTBEAT_SECONDS', 0.05)

    async def fake(**kwargs):
        await kwargs['emit']('stage_start', {'label': '正在设计分镜'})
        await kwargs['emit']('storyboard_stream', {'phase': 'content', 'chunk': '先看见'})
        await asyncio.sleep(0.2)
        await kwargs['emit']('storyboard_stream', {'phase': 'tool_args', 'tool': 'replace_storyboard', 'tool_call_id': 'shot', 'chunk': '镜头标题'})
        return {'message': '完成', 'shots': None}

    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    response = call(drama)
    text = response.text
    content_at = text.index('先看见')
    args_at = text.index('镜头标题')
    assert response.status_code == 200
    assert text.startswith(': heartbeat')
    assert content_at < args_at
    assert ': heartbeat' in text[content_at:args_at]
    assert parse_sse(text)[-1][0] == 'storyboard_done'


def test_stale_chapter_is_conflict_and_never_calls_model(drama, monkeypatch):
    async def fail(**kwargs):
        pytest.fail('stale request invoked model')
    monkeypatch.setattr(short_drama, 'design_storyboard', fail)
    response = call(drama, source_content='旧原文')
    assert response.status_code == 409


def test_chapter_changed_during_generation_discards_result(drama, monkeypatch, db_session):
    async def fake(**kwargs):
        drama[3].content = '模型运行期间更新的正文'
        db_session.commit()
        return {'message': '过期方案', 'shots': None}
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    response = call(drama)
    events = parse_sse(response.text)
    assert events[-1] == ('error', {'message': '设计期间章节原文已变化，请刷新后重新设计'})
    assert all(name != 'storyboard_done' for name, _data in events)


def test_model_failure_returns_error_without_substituting_a_plan(drama, monkeypatch):
    async def fail(**kwargs):
        raise RuntimeError('模型调用失败')
    monkeypatch.setattr(short_drama, 'design_storyboard', fail)
    response = call(drama)
    events = parse_sse(response.text)
    assert events[-1] == ('error', {'message': '模型调用失败'})
    assert all(name != 'storyboard_done' for name, _data in events)
