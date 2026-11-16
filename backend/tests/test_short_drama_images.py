import asyncio
import base64
import json
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from main import app
from tests.test_short_drama_api import drama
from services.auth_service import auth_service

client = TestClient(app)


def request(drama, method, path, body=None, user=None):
    return client.request(method, f'/api/works/{drama[2].id}/short-drama' + path, json=body,
        headers={'Authorization': 'Bearer ' + auth_service.create_access_token((user or drama[0]).id)})


def prepare(drama):
    response = request(drama, 'PUT', '/portraits', {'revision': 0, 'portraits': [
        {'id': 'portrait-1', 'roleId': drama[4].id, 'prompt': '中文完整立绘提示词', 'imagePath': ''}]})
    assert response.status_code == 200


def test_image_job_snapshots_saved_prompt_and_validates_owner_and_parameters(drama, monkeypatch, db_session):
    from services import short_drama_image as image
    from models.short_drama import DramaImageJob
    prepare(drama)
    started = []
    monkeypatch.setattr(image, 'start_job', started.append)
    url = '/portraits/portrait-1/generate'
    body = dict(width=768, height=1024, seed=123)
    assert request(drama, 'POST', url, body, user=drama[1]).status_code == 404
    assert request(drama, 'POST', '/portraits/missing/generate', body).status_code == 404
    assert request(drama, 'POST', url, {**body, 'width': 767}).status_code == 422
    response = request(drama, 'POST', url, body)
    assert response.status_code == 200
    job = response.json()
    assert job['status'] == 'queued' and started == [job['id']]
    saved = db_session.get(DramaImageJob, job['id'])
    assert (saved.prompt, saved.width, saved.height, saved.seed) == ('中文完整立绘提示词', 768, 1024, 123)
    assert request(drama, 'POST', url, body).status_code == 409
    assert request(drama, 'GET', '/image-jobs').json()[0]['id'] == job['id']
    assert request(drama, 'GET', '/image-jobs', user=drama[1]).status_code == 404


def test_image_worker_downloads_result_saves_portrait_and_preserves_old_image_on_failure(drama, monkeypatch, tmp_path, db_session):
    from services import short_drama_image as image
    from models.short_drama import DramaPortrait, DramaImageJob
    from services.short_drama_store import recover_interrupted
    prepare(drama)
    monkeypatch.setattr(image, 'start_job', lambda _: None)
    async def success(job):
        path = tmp_path / 'portrait.png'
        path.write_bytes(b'png-bytes')
        return path
    monkeypatch.setattr(image, 'generate_remote', success)
    job = request(drama, 'POST', '/portraits/portrait-1/generate', {}).json()
    asyncio.run(image.run_job(job['id']))
    assert request(drama, 'GET', '/image-jobs').json()[0]['status'] == 'succeeded'
    response = request(drama, 'GET', '/portraits/portrait-1/file')
    assert response.content == b'png-bytes' and response.headers['content-type'] == 'image/png'
    assert request(drama, 'GET', '/portraits/portrait-1/file', user=drama[1]).status_code == 404
    async def fail(job):
        raise RuntimeError('缺少推理环境 .venv-image')
    monkeypatch.setattr(image, 'generate_remote', fail)
    retry = request(drama, 'POST', '/portraits/portrait-1/generate', {}).json()
    asyncio.run(image.run_job(retry['id']))
    failed = request(drama, 'GET', '/image-jobs').json()[0]
    assert failed['status'] == 'failed' and '.venv-image' in failed['error']
    assert request(drama, 'GET', '/portraits/portrait-1/file').content == b'png-bytes'
    interrupted = request(drama, 'POST', '/portraits/portrait-1/generate', {}).json()
    recover_interrupted(db_session)
    db_session.expire_all()
    assert db_session.get(DramaImageJob, interrupted['id']).status == 'failed'
    assert db_session.get(DramaPortrait, 'portrait-1').image_path == str(tmp_path / 'portrait.png')


@pytest.mark.parametrize('environment', ['development', 'production'])
def test_ssh_image_generation_passes_full_prompt_offline_script_and_downloads(monkeypatch, tmp_path, environment):
    from services import short_drama_image as image
    from config import settings
    monkeypatch.setattr(settings, 'environment', environment)
    job = SimpleNamespace(id='image-1', prompt='完整中文\n' * 5000 + '`echo x` $(echo y)', width=768, height=1024, seed=3)
    calls = []
    async def command(args, input_data=None):
        calls.append((args, input_data))
        if input_data:
            script = input_data.decode()
            assert base64.b64encode(job.prompt.encode()).decode() in script
            assert job.prompt not in script
            assert 'generate_image.sh' in script and '--width 768' in script and '--wait' in script
            assert '--image-model' not in script  # 使用远端脚本默认的 Qwen。
            return json.dumps({'result_file': '/remote/result.json'})
        if args[0] == 'ssh':
            return json.dumps({'status': 'succeeded'})
        return ''
    monkeypatch.setattr(image, 'run_command', command)
    monkeypatch.setattr(image, 'IMAGE_DIR', tmp_path)
    path = asyncio.run(image.generate_remote(job))
    assert path == tmp_path / 'image-1.png'
    assert calls[-2][0][0] == 'scp'
    assert calls[-1][0][0] == 'ssh' and calls[-1][0][-1].startswith('rm -f -- ')
    async def failed(args, input_data=None):
        if input_data:
            return json.dumps({'result_file': '/remote/result.json'})
        return json.dumps({'status': 'failed', 'error': '显存不足'})
    monkeypatch.setattr(image, 'run_command', failed)
    import pytest
    with pytest.raises(RuntimeError, match='显存不足'):
        asyncio.run(image.generate_remote(job))


def test_empty_portrait_prompt_does_not_submit_a_job(drama, monkeypatch, db_session):
    from services import short_drama_image as image
    from models.short_drama import DramaPortrait
    prepare(drama)
    row = db_session.get(DramaPortrait, 'portrait-1')
    row.prompt = '  \n  '
    db_session.commit()
    started = []
    monkeypatch.setattr(image, 'start_job', started.append)
    assert request(drama, 'POST', '/portraits/portrait-1/generate', {}).status_code == 400
    assert started == []


def test_startup_creates_jobs_after_legacy_portrait_table_upgrade(drama, db_session):
    import database
    from sqlalchemy import text, inspect
    db_session.commit()
    with database.engine.begin() as connection:
        connection.execute(text('DROP TABLE drama_image_jobs'))
        connection.execute(text('ALTER TABLE drama_shot_roles DROP COLUMN portrait_id'))
        connection.execute(text('DROP TABLE drama_portraits'))
        connection.execute(text('''CREATE TABLE drama_portraits (
            workspace_id VARCHAR(36) REFERENCES drama_workspaces(id), role_id VARCHAR(36) REFERENCES nodes(id),
            description TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (workspace_id, role_id))'''))
    database.init_db()
    database.init_db()
    columns = {c['name']: str(c['type']) for c in inspect(database.engine).get_columns('drama_image_jobs')}
    assert {'portrait_id', 'work_id', 'prompt', 'width', 'height', 'seed', 'status'} <= columns.keys()
    assert all('JSON' not in kind for kind in columns.values())
    assert 'id' in {c['name'] for c in inspect(database.engine).get_columns('drama_portraits')}
