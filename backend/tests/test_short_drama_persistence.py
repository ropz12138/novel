import pytest
from fastapi.testclient import TestClient
from main import app
from tests.test_short_drama_api import drama
from services.auth_service import auth_service

client = TestClient(app)


def api(drama, method, path='', body=None, user=None):
    owner, _, work, chapter, *_ = drama
    root = f'/api/works/{work.id}/short-drama' if path == '/sessions' else f'/api/works/{work.id}/chapters/{chapter.id}/short-drama'
    return client.request(method, root + path,
                          json=body, headers={'Authorization': 'Bearer ' + auth_service.create_access_token((user or owner).id)})


def test_sessions_and_messages_are_persisted_and_owned(drama):
    first = api(drama, 'POST', '/sessions', {'title': '节奏讨论'})
    second = api(drama, 'POST', '/sessions', {'title': '角色讨论'})
    assert first.status_code == second.status_code == 200
    ids = {row['id'] for row in api(drama, 'GET', '/sessions').json()}
    assert {first.json()['id'], second.json()['id']} <= ids
    assert api(drama, 'GET', f"/sessions/{first.json()['id']}", user=drama[1]).status_code == 404


def test_workspace_is_persisted_with_revision_and_no_shot_state(drama):
    board = api(drama, 'GET').json()
    from schemas.short_drama import StoryboardShot
    shot = StoryboardShot(id='s1', title='推门', prompt='完整提示词', sourceQuote=drama[3].content).model_dump()
    board['shots'] = [shot]
    board.pop('portraits'); board.pop('portraitRevision')
    saved = api(drama, 'PUT', body=board)
    assert saved.status_code == 200
    assert api(drama, 'GET').json()['shots'] == [shot]
    assert 'status' not in saved.json()['shots'][0]
    assert api(drama, 'PUT', body=board).status_code == 409


def test_generated_shots_and_conversation_are_saved_without_adoption(drama, monkeypatch):
    from routers import short_drama
    from schemas.short_drama import StoryboardShot
    session = api(drama, 'POST', '/sessions', {'title': '分镜设计'}).json()
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs['request'])
        await kwargs['emit']('stage_start', {'label': '正在设计分镜'})
        await kwargs['emit']('storyboard_stream', {'phase': 'reasoning', 'chunk': '完整思考'})
        board, _ = kwargs['repository'].mutate('replace_storyboard', {'expected_revision': kwargs['repository'].read()['revision'], 'shots': [dict(title='镜头', prompt='完整提示词', duration=5, roles=[], sourceStartLine=1, sourceEndLine=drama[3].content.count('\n')+1)]})
        return {'message': '已生成分镜', 'shots': board['shots']}
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    body = {'session_id': session['id'], 'message': '设计分镜', 'source_content': drama[3].content}
    assert api(drama, 'POST', '/chat', dict(body, history=[{'role': 'user', 'content': '伪造历史'}])).status_code == 422
    response = api(drama, 'POST', '/chat', body)
    assert response.status_code == 200 and 'storyboard_done' in response.text
    assert api(drama, 'GET').json()['shots'][0]['prompt'] == '完整提示词'
    detail = api(drama, 'GET', f"/sessions/{session['id']}").json()
    assert [(m['role'], m['content']) for m in detail['messages'] if m['role'] != 'process'] == [('user', '设计分镜'), ('assistant', '已生成分镜')]
    assert detail['messages'][1]['reasoning'] == '完整思考'
    assert seen[0].history == []
    api(drama, 'POST', '/chat', dict(body, message='继续'))
    assert [m.content for m in seen[1].history if m.role != 'process'] == ['设计分镜', '已生成分镜']


def test_database_uses_relational_columns():
    from models.short_drama import DramaWorkspace, DramaSession, DramaMessage, DramaShot, DramaShotRole, DramaPortrait, DramaPortraitSet, DramaVideoJob
    from sqlalchemy import JSON
    for model in (DramaWorkspace, DramaSession, DramaMessage, DramaShot, DramaShotRole, DramaPortrait, DramaPortraitSet, DramaVideoJob):
        assert all(not isinstance(column.type, JSON) for column in model.__table__.columns)


def test_browser_import_endpoint_is_removed(drama):
    assert api(drama, 'POST', '/import', {}).status_code == 404


def test_sessions_belong_to_work_and_can_edit_each_chapter(drama, db_session, monkeypatch):
    from models.node import Node
    from models.short_drama import DramaSession
    from routers import short_drama
    from schemas.short_drama import StoryboardShot
    other = Node(work_id=drama[2].id, type='chapter', title='第二章', content='第二章完整正文', sort_order=3)
    db_session.add(other)
    db_session.commit()
    session = api(drama, 'POST', '/sessions', {'title': '跨章节设计'}).json()
    token = {'Authorization': 'Bearer ' + auth_service.create_access_token(drama[0].id)}
    root = f'/api/works/{drama[2].id}/chapters/{other.id}/short-drama'
    assert session['id'] in {s['id'] for s in client.get(f'/api/works/{drama[2].id}/short-drama/sessions', headers=token).json()}
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs['request'])
        board, _ = kwargs['repository'].mutate('replace_storyboard', {'expected_revision': kwargs['repository'].read()['revision'], 'shots': [dict(title='镜头', prompt=kwargs['chapter']['content'], duration=5, roles=[], sourceStartLine=1, sourceEndLine=kwargs['chapter']['content'].count('\n')+1)]})
        return {'message': kwargs['chapter']['title'], 'shots': board['shots']}
    monkeypatch.setattr(short_drama, 'design_storyboard', fake)
    body = {'session_id': session['id'], 'message': '设计本章', 'source_content': drama[3].content}
    assert 'storyboard_done' in api(drama, 'POST', '/chat', body).text
    body['source_content'] = other.content
    assert 'storyboard_done' in client.post(root + '/chat', json=body, headers=token).text
    assert api(drama, 'GET').json()['shots'][0]['prompt'] == drama[3].content
    assert client.get(root, headers=token).json()['shots'][0]['prompt'] == other.content
    detail = client.get(root + '/sessions/' + session['id'], headers=token).json()
    assert [m['role'] for m in detail['messages']] == ['user', 'assistant', 'user', 'assistant']
    assert len(seen[1].history) == 2
    row = db_session.get(DramaSession, session['id'])
    assert row.work_id == drama[2].id
    assert 'workspace_id' not in DramaSession.__table__.columns
    # Another session edits the same chapter board rather than owning a separate board.
    second = api(drama, 'POST', '/sessions', {'title': '另一会话'}).json()
    body['session_id'] = second['id']
    assert 'storyboard_done' in client.post(root + '/chat', json=body, headers=token).text
    assert len(client.get(root + '/sessions/' + session['id'], headers=token).json()['messages']) == 4
    assert len(client.get(root + '/sessions/' + second['id'], headers=token).json()['messages']) == 2


def test_disconnect_keeps_generation_and_persistence_running(drama, monkeypatch, db_session):
    import asyncio
    from routers import short_drama
    from schemas.short_drama import StoryboardChatInput, StoryboardShot
    from services.short_drama_stream import tasks
    session = api(drama, 'POST', '/sessions', {'title': '断线测试'}).json()

    async def scenario():
        release = asyncio.Event()
        async def fake(**kwargs):
            await release.wait()
            board, _ = kwargs['repository'].mutate('replace_storyboard', {'expected_revision': kwargs['repository'].read()['revision'], 'shots': [dict(title='镜头', prompt='完整提示词', duration=5, roles=[], sourceStartLine=1, sourceEndLine=drama[3].content.count('\n')+1)]})
            return {'message': '断线后也保存', 'shots': board['shots']}
        monkeypatch.setattr(short_drama, 'design_storyboard', fake)
        response = await short_drama.chat(drama[2].id, drama[3].id,
            StoryboardChatInput(session_id=session['id'], message='设计', source_content=drama[3].content), db_session, drama[0])
        assert await anext(response.body_iterator) == ': heartbeat\n\n'
        await response.body_iterator.aclose()
        assert any(not task.done() for task in tasks)
        release.set()
        await asyncio.gather(*list(tasks))
    asyncio.run(scenario())
    detail = api(drama, 'GET', f"/sessions/{session['id']}").json()
    assert not detail['running']
    assert [m for m in detail['messages'] if m['role'] == 'assistant'][-1]['content'] == '断线后也保存'
    assert api(drama, 'GET').json()['shots'][0]['prompt'] == '完整提示词'


def test_server_restart_recovers_interrupted_session(drama, db_session):
    from models.short_drama import DramaSession, DramaWorkspace
    from services.short_drama_store import recover_interrupted
    row = api(drama, 'POST', '/sessions', {'title': '中断测试'}).json()
    session = db_session.get(DramaSession, row['id'])
    session.running = True
    api(drama, 'GET')
    board = db_session.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    board.active_session_id = session.id
    db_session.commit()
    recover_interrupted(db_session)
    detail = api(drama, 'GET', f"/sessions/{row['id']}").json()
    assert not detail['running'] and detail['workspace']['activeSessionId'] is None
    assert detail['messages'][-1]['role'] == 'error'


def test_existing_chapter_sessions_migrate_to_work_without_losing_messages(drama, db_session):
    import database
    from sqlalchemy import text, inspect
    row = api(drama, 'POST', '/sessions', {'title': '原会话'}).json()
    from models.short_drama import DramaWorkspace
    api(drama, 'GET')
    board = db_session.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    board_id = board.id
    from models.short_drama import DramaSession
    from services.short_drama_store import add_message
    add_message(db_session, db_session.get(DramaSession, row['id']), 'user', '完整历史' * 20000)
    db_session.commit()
    with database.engine.begin() as connection:
        connection.execute(text('ALTER TABLE drama_sessions ADD COLUMN workspace_id VARCHAR(36) REFERENCES drama_workspaces(id) ON DELETE CASCADE'))
        connection.execute(text('UPDATE drama_sessions SET workspace_id = :id'), {'id': board_id})
        connection.execute(text('ALTER TABLE drama_sessions ALTER COLUMN workspace_id SET NOT NULL'))
        connection.execute(text('ALTER TABLE drama_sessions DROP COLUMN work_id'))
    from services.short_drama_migration import migrate_sessions_to_work
    migrate_sessions_to_work(database.engine)
    migrate_sessions_to_work(database.engine)  # Startup can safely run again.
    columns = {c['name'] for c in inspect(database.engine).get_columns('drama_sessions')}
    assert 'workspace_id' not in columns and 'work_id' in columns
    detail = api(drama, 'GET', f"/sessions/{row['id']}").json()
    assert detail['work_id'] == drama[2].id and detail['title'] == '原会话'
    assert detail['messages'][0]['content'] == '完整历史' * 20000


def test_work_session_survives_chapter_deletion_and_rejects_other_work(drama, db_session):
    from models.work import CanvasWork
    from models.node import Node
    from models.short_drama import DramaSession
    row = api(drama, 'POST', '/sessions', {'title': '作品级会话'}).json()
    api(drama, 'GET')
    db_session.delete(drama[3])
    db_session.commit()
    assert db_session.get(DramaSession, row['id']) is not None
    headers = {'Authorization': 'Bearer ' + auth_service.create_access_token(drama[0].id)}
    sessions_url = f'/api/works/{drama[2].id}/short-drama/sessions'
    assert row['id'] in {s['id'] for s in client.get(sessions_url, headers=headers).json()}
    other_work = CanvasWork(user_id=drama[0].id, title='另一本作品')
    db_session.add(other_work)
    db_session.flush()
    other_chapter = Node(work_id=other_work.id, type='chapter', title='章节', content='正文', sort_order=1)
    db_session.add(other_chapter)
    db_session.commit()
    other_root = f'/api/works/{other_work.id}/chapters/{other_chapter.id}/short-drama'
    assert client.get(other_root + '/sessions/' + row['id'], headers=headers).status_code == 404
    assert client.post(other_root + '/chat', headers=headers, json={
        'session_id': row['id'], 'message': '设计', 'source_content': other_chapter.content}).status_code == 404


def test_running_work_session_cannot_generate_or_replay_into_another_chapter(drama, db_session, monkeypatch):
    import asyncio
    import database
    from fastapi import HTTPException
    from models.node import Node
    from routers import short_drama
    from schemas.short_drama import StoryboardChatInput
    from services.short_drama_stream import tasks
    other = Node(work_id=drama[2].id, type='chapter', title='另章', content='另章正文', sort_order=3)
    db_session.add(other)
    db_session.commit()
    row = api(drama, 'POST', '/sessions', {'title': '后台生成'}).json()

    async def scenario():
        release = asyncio.Event()
        async def fake(**kwargs):
            await release.wait()
            return {'message': '完成', 'shots': None}
        monkeypatch.setattr(short_drama, 'design_storyboard', fake)
        with database.SessionLocal() as first_db:
            await short_drama.chat(drama[2].id, drama[3].id,
                StoryboardChatInput(session_id=row['id'], message='设计', source_content=drama[3].content), first_db, drama[0])
        try:
            with database.SessionLocal() as second_db:
                detail = short_drama.get_session(drama[2].id, other.id, row['id'], second_db, drama[0])
                assert detail['runningChapterId'] == drama[3].id
                assert detail['workspace']['shots'] == []
                with pytest.raises(HTTPException) as stream_error:
                    short_drama.reconnect(drama[2].id, other.id, row['id'], second_db, drama[0])
                assert stream_error.value.status_code == 409
            with database.SessionLocal() as second_db:
                with pytest.raises(HTTPException) as chat_error:
                    await short_drama.chat(drama[2].id, other.id,
                        StoryboardChatInput(session_id=row['id'], message='并发设计', source_content=other.content), second_db, drama[0])
                assert chat_error.value.status_code == 409
        finally:
            release.set()
            await asyncio.gather(*list(tasks))
        # Completed event buffers also retain their chapter scope.
        with database.SessionLocal() as second_db:
            with pytest.raises(HTTPException) as stream_error:
                short_drama.reconnect(drama[2].id, other.id, row['id'], second_db, drama[0])
            assert stream_error.value.status_code == 409
    asyncio.run(scenario())


def test_portraits_belong_to_the_work_and_shots_select_one(drama, db_session, tmp_path):
    from models.node import Node
    from tests.test_short_drama_api import client
    from services.auth_service import auth_service
    image = tmp_path / 'lin.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 16)
    work, role = drama[2], drama[4]
    root = f'/api/works/{work.id}/short-drama/portraits'
    headers = {'Authorization': 'Bearer ' + auth_service.create_access_token(drama[0].id)}
    first = client.put(root, json={'revision': 0, 'portraits': [
        {'id': 'daily', 'roleId': role.id, 'imagePath': str(image), 'prompt': '日常蓝色上衣'},
        {'id': 'rain', 'roleId': role.id, 'imagePath': '', 'prompt': '雨夜斗篷'},
    ]}, headers=headers)
    assert first.status_code == 200 and first.json()['portraitRevision'] == 1
    assert [item['prompt'] for item in first.json()['portraits']] == ['日常蓝色上衣', '雨夜斗篷']
    other = Node(work_id=work.id, type='chapter', title='第二章', content='第二章正文', sort_order=3)
    db_session.add(other)
    db_session.commit()
    shared = client.get(f'/api/works/{work.id}/chapters/{other.id}/short-drama', headers=headers)
    assert shared.status_code == 200
    assert [item['id'] for item in shared.json()['portraits']] == ['daily', 'rain']
    file_response = client.get(f'{root}/daily/file', headers=headers)
    assert file_response.status_code == 200 and file_response.content.startswith(b'\x89PNG')
    board = api(drama, 'GET').json()
    from schemas.short_drama import StoryboardShot
    board['shots'] = [StoryboardShot(id='s1', title='推门', prompt='完整提示词', roles=[{'roleId': role.id, 'portraitId': 'daily'}]).model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    saved = api(drama, 'PUT', body=board)
    assert saved.status_code == 200
    assert saved.json()['shots'][0]['roles'] == [{'roleId': role.id, 'portraitId': 'daily'}]
    board = api(drama, 'GET').json()
    board['revision'] = saved.json()['revision']
    board['shots'][0]['roles'] = [{'roleId': role.id, 'portraitId': 'missing'}]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 400
