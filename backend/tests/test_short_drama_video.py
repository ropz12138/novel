import asyncio
import json
import pytest
from tests.test_short_drama_api import drama
from tests.test_short_drama_persistence import api


def test_video_queue_follows_shot_order_and_puts_the_newer_attempt_first(drama, monkeypatch, db_session):
    from models.short_drama import DramaVideoJob
    from schemas.short_drama import StoryboardShot
    from services import short_drama_video as video
    board = api(drama, 'GET').json()
    board['shots'] = [
        StoryboardShot(id='s1', title='第一镜', prompt='甲').model_dump(),
        StoryboardShot(id='s2', title='第二镜', prompt='乙').model_dump(),
    ]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    created = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert created.status_code == 200
    blocked = api(drama, 'POST', '/videos', {'shot_ids': ['s2']})
    assert blocked.status_code == 409 and blocked.json()['detail'] == '已有生图或生视频正在处理'
    job = db_session.get(DramaVideoJob, created.json()[0]['id'])
    job.status = 'succeeded'
    db_session.commit()
    second = api(drama, 'POST', '/videos', {'shot_ids': ['s2']})
    assert second.status_code == 200
    db_session.get(DramaVideoJob, second.json()[0]['id']).status = 'succeeded'
    db_session.commit()
    assert api(drama, 'POST', '/videos', {'shot_ids': ['s2'], 'quality': 'preview'}).status_code == 200
    assert [(row['shot_id'], row['quality']) for row in api(drama, 'GET', '/videos').json()] == [
        ('s1', 'final'), ('s2', 'preview'), ('s2', 'final')]
    batch = api(drama, 'POST', '/videos', {'shot_ids': ['s1', 's2'], 'quality': 'preview'})
    assert batch.status_code == 400 and batch.json()['detail'] == '一次只能生成一个镜头'


def test_active_image_blocks_video_and_active_video_blocks_image(drama, monkeypatch, db_session):
    from models.node import Node
    from models.short_drama import DramaImageJob, DramaVideoJob
    from schemas.short_drama import StoryboardShot
    from services.auth_service import auth_service
    from services import short_drama_image as image
    from services import short_drama_video as video
    from tests.test_short_drama_images import request
    from tests.test_short_drama_persistence import client
    monkeypatch.setattr(image, 'start_job', lambda job_id: None)
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    portraits = request(drama, 'PUT', '/portraits', {'revision': 0, 'portraits': [
        {'id': 'p1', 'roleId': drama[4].id, 'prompt': '第一张立绘', 'imagePath': ''},
        {'id': 'p2', 'roleId': drama[4].id, 'prompt': '第二张立绘', 'imagePath': ''},
    ]})
    assert portraits.status_code == 200
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整画面').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    other = Node(work_id=drama[2].id, type='chapter', title='第二章', content='另一章', sort_order=3)
    db_session.add(other); db_session.commit()
    headers = {'Authorization': 'Bearer ' + auth_service.create_access_token(drama[0].id)}
    other_root = f'/api/works/{drama[2].id}/chapters/{other.id}/short-drama'
    other_board = client.get(other_root, headers=headers).json()
    other_board['shots'] = [StoryboardShot(id='s1', prompt='另一章画面').model_dump()]
    other_board.pop('portraits'); other_board.pop('portraitRevision')
    assert client.put(other_root, json=other_board, headers=headers).status_code == 200
    image_job = request(drama, 'POST', '/portraits/p1/generate', {})
    assert image_job.status_code == 200
    for blocked in (
        request(drama, 'POST', '/portraits/p2/generate', {}),
        api(drama, 'POST', '/videos', {'shot_ids': ['s1']}),
        client.post(other_root + '/videos', json={'shot_ids': ['s1']}, headers=headers),
    ):
        assert blocked.status_code == 409 and blocked.json()['detail'] == '已有生图或生视频正在处理'
    db_session.get(DramaImageJob, image_job.json()['id']).status = 'succeeded'
    db_session.commit()
    video_job = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert video_job.status_code == 200
    for blocked in (
        request(drama, 'POST', '/portraits/p2/generate', {}),
        client.post(other_root + '/videos', json={'shot_ids': ['s1']}, headers=headers),
    ):
        assert blocked.status_code == 409 and blocked.json()['detail'] == '已有生图或生视频正在处理'
    db_session.get(DramaVideoJob, video_job.json()[0]['id']).status = 'succeeded'
    db_session.commit()
    assert request(drama, 'POST', '/portraits/p2/generate', {}).status_code == 200


def test_video_entry_creates_snapshot_and_rejects_foreign_or_duplicate_jobs(drama, monkeypatch):
    from services import short_drama_video as video
    from schemas.short_drama import StoryboardShot
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', title='推门', prompt='完整视频提示词', sourceQuote=drama[3].content).model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    started = []
    monkeypatch.setattr(video, 'start_jobs', lambda ids: started.extend(ids))
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert response.status_code == 200
    job = response.json()[0]
    assert job['status'] == 'queued' and started == [job['id']]
    assert api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).status_code == 409
    assert api(drama, 'POST', '/videos', {'shot_ids': ['missing']}).status_code == 404
    assert api(drama, 'GET', '/videos', user=drama[1]).status_code == 404
    assert api(drama, 'GET', f"/videos/{job['id']}/file").status_code == 409


def test_remote_generation_preserves_prompt_and_never_embeds_it_in_shell(monkeypatch, tmp_path):
    from services import short_drama_video as video
    from types import SimpleNamespace
    prompt = '完整提示词\n' + '细节' * 10000 + '`touch nope`; $(echo nope)'
    job = SimpleNamespace(id='job-1', prompt=prompt, duration=5, width=960, height=544, seed=42,
                          mode='turbo', input_mode='text', reference_paths='', first_frame='', last_frame='')
    calls = []
    async def command(args, input_data=None):
        calls.append((args, input_data))
        if input_data:
            import base64
            assert base64.b64encode(prompt.encode()).decode() in input_data.decode()
            assert prompt not in input_data.decode()
            return json.dumps({'result_file': '/remote/result.json'})
        if args[0] == 'ssh':
            return json.dumps({'status': 'succeeded'})
        return ''
    monkeypatch.setattr(video, 'run_command', command)
    monkeypatch.setattr(video, 'VIDEO_DIR', tmp_path)
    result = asyncio.run(video.generate_remote(job))
    assert str(result).endswith('job-1.mp4')
    assert calls[-2][0][0] == 'scp'
    assert calls[-1][0][0] == 'ssh' and calls[-1][0][-1].startswith('rm -f -- ')


def test_video_worker_saves_success_failure_and_protected_download(drama, monkeypatch, tmp_path):
    from services import short_drama_video as video
    from schemas.short_drama import StoryboardShot
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整提示词').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    api(drama, 'PUT', body=board)
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    async def success(job):
        path = tmp_path / 'test.mp4'
        path.write_bytes(b'video-data')
        return path
    monkeypatch.setattr(video, 'generate_remote', success)
    job = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    asyncio.run(video.run_job(job['id']))
    response = api(drama, 'GET', f"/videos/{job['id']}/file")
    assert response.status_code == 200 and response.content == b'video-data'
    assert api(drama, 'GET', f"/videos/{job['id']}/file", user=drama[1]).status_code == 404
    async def fail(job):
        raise RuntimeError('集群作业失败')
    monkeypatch.setattr(video, 'generate_remote', fail)
    retry = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    asyncio.run(video.run_job(retry['id']))
    failed = next(j for j in api(drama, 'GET', '/videos').json() if j['id'] == retry['id'])
    assert failed['status'] == 'failed' and failed['error'] == '集群作业失败'


def test_reference_job_uses_selected_portrait_snapshot_without_manual_paths(drama, monkeypatch, tmp_path, db_session):
    from services import short_drama_video as video
    from models.short_drama import DramaPortrait, DramaVideoJob
    from schemas.short_drama import StoryboardShot
    portrait = tmp_path / 'portrait.png'
    portrait.write_bytes(b'original-image')
    from models.node import Node
    second_role = Node(id='00000000-0000-0000-0000-000000000001', work_id=drama[2].id, type='character', title='第二角色', sort_order=3)
    db_session.add(second_role); db_session.flush()
    second_image = tmp_path / 'second.png'
    second_image.write_bytes(b'second-image')
    db_session.add(DramaPortrait(id='p2', work_id=drama[2].id, role_id=second_role.id, image_path=str(second_image), prompt='第二立绘'))
    db_session.add(DramaPortrait(id='p1', work_id=drama[2].id, role_id=drama[4].id, image_path=str(portrait), prompt='立绘'))
    db_session.commit()
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='图1的人物缓缓转身', inputMode='reference',
        roles=[dict(roleId=drama[4].id, portraitId='p1'), dict(roleId=second_role.id, portraitId='p2')], referencePaths='refs/obsolete.png').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert response.status_code == 200, response.text
    job = db_session.get(DramaVideoJob, response.json()[0]['id'])
    assert job.reference_paths.splitlines() == [str(second_image), str(portrait)]
    db_session.get(DramaPortrait, 'p1').image_path = '/newer-image.png'
    db_session.commit()
    db_session.refresh(job)
    assert job.reference_paths.splitlines() == [str(second_image), str(portrait)]
    assert portrait.read_bytes() == b'original-image'


@pytest.mark.parametrize('image_path,select_portrait', [('', False), ('', True), ('/missing/portrait.png', True)])
def test_reference_mode_requires_selected_generated_image(drama, monkeypatch, db_session, image_path, select_portrait):
    from services import short_drama_video as video
    from models.short_drama import DramaPortrait
    from schemas.short_drama import StoryboardShot
    db_session.add(DramaPortrait(id='p1', work_id=drama[2].id, role_id=drama[4].id, image_path=image_path, prompt='立绘'))
    db_session.commit()
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='画面', inputMode='reference',
        roles=[dict(roleId=drama[4].id, portraitId='p1' if select_portrait else None)], referencePaths='refs/old.png').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    started = []
    monkeypatch.setattr(video, 'start_jobs', started.extend)
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    if not select_portrait:
        assert response.status_code == 200, response.text
        assert started == [response.json()[0]['id']]
        return
    assert response.status_code == 400
    assert '立绘' in response.json()['detail']
    assert not started


@pytest.mark.parametrize('failure', [None, 'upload', 'submit', 'render', 'download'])
def test_uploaded_references_keep_order_and_are_cleaned_after_success_or_failure(monkeypatch, tmp_path, failure):
    from services import short_drama_video as video
    from types import SimpleNamespace
    first, second = tmp_path / 'first portrait.png', tmp_path / 'second.jpg'
    first.write_bytes(b'first'); second.write_bytes(b'second')
    job = SimpleNamespace(id='ref-job', prompt='完整提示词', duration=5, width=768, height=1024, seed=42,
        mode='turbo', input_mode='reference', reference_paths=f'{first}\n{second}', first_frame='', last_frame='')
    calls = []
    async def command(args, input_data=None):
        calls.append((args, input_data))
        if args[0] == 'scp' and args[-1].startswith(f'{video.HOST}:'):
            if failure == 'upload': raise RuntimeError('upload failed')
            return ''
        if input_data:
            script = input_data.decode()
            assert '--reference-images media_jobs_dev/novel_inputs/ref-job_refs/1.png media_jobs_dev/novel_inputs/ref-job_refs/2.jpg' in script
            assert str(first) not in script and str(second) not in script
            if failure == 'submit': raise RuntimeError('submit failed')
            return json.dumps({'result_file': '/remote/result.json'})
        if args[0] == 'ssh' and args[-1].startswith('cat '):
            return json.dumps({'status': 'failed', 'error': 'render failed'} if failure == 'render' else {'status': 'succeeded'})
        if args[0] == 'scp' and failure == 'download': raise RuntimeError('download failed')
        return ''
    monkeypatch.setattr(video, 'run_command', command)
    monkeypatch.setattr(video, 'VIDEO_DIR', tmp_path / 'videos')
    if failure:
        with pytest.raises(RuntimeError, match=f'{failure} failed'):
            asyncio.run(video.generate_remote(job))
    else:
        assert asyncio.run(video.generate_remote(job)) == tmp_path / 'videos/ref-job.mp4'
        uploads = [args for args, _ in calls if args[0] == 'scp' and args[-1].startswith(f'{video.HOST}:')]
        assert [args[-2] for args in uploads] == [str(first), str(second)]
    cleanup = calls[-1][0]
    assert cleanup[0] == 'ssh'
    assert cleanup[-1] == f'rm -rf -- {video.PROJECT}/media_jobs_dev/novel_inputs/ref-job_refs'
    assert first.read_bytes() == b'first' and second.read_bytes() == b'second'


def test_video_mode_comes_from_portraits_and_first_frame_source(drama, monkeypatch, tmp_path, db_session):
    from services import short_drama_video as video
    from models.short_drama import DramaPortrait, DramaVideoJob
    from schemas.short_drama import StoryboardShot
    image = tmp_path / 'portrait.png'
    image.write_bytes(b'image')
    db_session.add(DramaPortrait(id='p1', work_id=drama[2].id, role_id=drama[4].id, image_path=str(image), prompt='立绘'))
    db_session.commit()
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id=shot_id, prompt='完整画面', inputMode='text').model_dump() for shot_id in ['s1', 's2']]
    board['shots'][0]['roles'] = [dict(roleId=drama[4].id, portraitId='p1')]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert response.status_code == 200, response.text
    job = db_session.get(DramaVideoJob, response.json()[0]['id'])
    assert job.input_mode == 'reference' and job.reference_paths == str(image) and job.first_frame_shot_id == ''
    job.status = 'succeeded'
    db_session.commit()
    board = api(drama, 'GET').json()
    board['shots'][1]['roles'] = [dict(roleId=drama[4].id, portraitId='p1')]
    board['shots'][1]['firstFrameShotId'] = 's1'
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    started = []
    monkeypatch.setattr(video, 'start_jobs', started.extend)
    conflict = api(drama, 'POST', '/videos', {'shot_ids': ['s2'], 'quality': 'preview'})
    assert conflict.status_code == 400 and conflict.json()['detail'] == '参考图和首帧来源只能提供一种'
    assert not started


@pytest.mark.parametrize('shot_index,source_id', [(1, 's2'), (1, 'missing'), (0, 's2')])
def test_saved_first_frame_source_must_be_an_earlier_shot(drama, shot_index, source_id):
    from schemas.short_drama import StoryboardShot
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id=shot_id, prompt='完整画面').model_dump() for shot_id in ['s1', 's2']]
    board['shots'][shot_index]['inputMode'] = 'first_lock'
    board['shots'][shot_index]['firstFrameShotId'] = source_id
    board.pop('portraits'); board.pop('portraitRevision')
    response = api(drama, 'PUT', body=board)
    assert response.status_code == 400 and response.json()['detail'] == '首帧来源只能是排在前面的镜头'


def test_video_generation_rejects_a_stored_later_first_frame_source(drama, monkeypatch, db_session):
    from models.short_drama import DramaShot
    from schemas.short_drama import StoryboardShot
    from services import short_drama_video as video
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id=shot_id, prompt='完整画面').model_dump() for shot_id in ['s1', 's2']]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    row = db_session.query(DramaShot).filter_by(shot_id='s1').one()
    row.first_frame_shot_id = 's2'
    row.input_mode = 'first_lock'
    db_session.commit()
    monkeypatch.setattr(video, 'start_jobs', lambda ids: pytest.fail('later source started a job'))
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert response.status_code == 400 and response.json()['detail'] == '首帧来源只能是排在前面的镜头'


def test_delete_succeeded_video_removes_the_record_and_files(drama, tmp_path, db_session):
    from models.short_drama import DramaVideoJob, DramaWorkspace
    api(drama, 'GET')
    workspace = db_session.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    final_file, poster, preview_file, running_file = tmp_path / 'final.mp4', tmp_path / 'final.jpg', tmp_path / 'preview.mp4', tmp_path / 'running.mp4'
    for path, content in ((final_file, b'final'), (poster, b'frame'), (preview_file, b'preview'), (running_file, b'running')):
        path.write_bytes(content)
    final = DramaVideoJob(workspace_id=workspace.id, shot_id='s1', quality='final', title='成片', prompt='完整画面',
        duration=5, width=960, height=544, seed=1, mode='turbo', input_mode='text', status='succeeded', local_path=str(final_file))
    preview = DramaVideoJob(workspace_id=workspace.id, shot_id='s1', quality='preview', title='预览', prompt='完整画面',
        duration=5, width=480, height=272, seed=1, mode='turbo', input_mode='text', status='succeeded', local_path=str(preview_file))
    running = DramaVideoJob(workspace_id=workspace.id, shot_id='s1', quality='final', title='生成中', prompt='完整画面',
        duration=5, width=960, height=544, seed=1, mode='turbo', input_mode='text', status='running', local_path=str(running_file))
    db_session.add_all([final, preview, running]); db_session.commit()
    assert api(drama, 'DELETE', f'/videos/{final.id}', user=drama[1]).status_code == 404
    blocked = api(drama, 'DELETE', f'/videos/{running.id}')
    assert blocked.status_code == 409 and blocked.json()['detail'] == '只能删除已生成的视频'
    assert running_file.read_bytes() == b'running'
    deleted = api(drama, 'DELETE', f'/videos/{final.id}')
    assert deleted.status_code == 204 and deleted.content == b''
    assert not final_file.exists() and not poster.exists() and preview_file.read_bytes() == b'preview'
    assert api(drama, 'GET', f'/videos/{final.id}/file').status_code == 404
    assert api(drama, 'GET', f'/videos/{final.id}/poster').status_code == 404
    assert {row['id'] for row in api(drama, 'GET', '/videos').json()} == {preview.id, running.id}
    assert api(drama, 'DELETE', f'/videos/{final.id}').status_code == 404


def test_first_lock_requires_an_existing_source_file_and_records_the_source_shot(drama, monkeypatch, tmp_path, db_session):
    from services import short_drama_video as video
    from models.short_drama import DramaVideoJob
    from schemas.short_drama import StoryboardShot
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id=shot_id, prompt='完整画面').model_dump() for shot_id in ['s1', 's2']]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    async def generate(job):
        path = tmp_path / f'{job.id}.mp4'
        path.write_bytes(b'source-video')
        return path
    monkeypatch.setattr(video, 'generate_remote', generate)
    source = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    asyncio.run(video.run_job(source['id']))
    board = api(drama, 'GET').json()
    board['shots'][1]['inputMode'] = 'first_lock'
    board['shots'][1]['firstFrameShotId'] = 's1'
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    started = []
    monkeypatch.setattr(video, 'start_jobs', started.extend)
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s2']})
    assert response.status_code == 200, response.text
    job = db_session.get(DramaVideoJob, response.json()[0]['id'])
    assert job.input_mode == 'first_lock' and job.first_frame_shot_id == 's1'
    assert job.first_frame == '' and job.last_frame == '' and job.reference_paths == ''
    assert started == [job.id]
    job.status = 'succeeded'
    db_session.commit()
    path = tmp_path / f"{source['id']}.mp4"
    path.unlink()
    monkeypatch.setattr(video, 'start_jobs', lambda ids: pytest.fail('missing source file started a job'))
    missing = api(drama, 'POST', '/videos', {'shot_ids': ['s2'], 'quality': 'preview'})
    assert missing.status_code == 400 and missing.json()['detail'] == '来源镜头还没有可使用的成片'


def test_removed_frames_mode_is_reset_before_first_lock(drama, db_session):
    from models.short_drama import DramaShot, DramaWorkspace
    from services.short_drama_migration import upgrade_first_frame_lock
    import database
    api(drama, 'GET')
    workspace = db_session.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    db_session.add(DramaShot(workspace_id=workspace.id, shot_id='old', sort_order=0, input_mode='frames', first_frame='/cluster/a.png', last_frame='/cluster/b.png'))
    db_session.commit()
    upgrade_first_frame_lock(database.engine)
    db_session.expire_all()
    shot = db_session.query(DramaShot).filter_by(shot_id='old').one()
    assert shot.input_mode == 'text' and shot.first_frame == '' and shot.last_frame == '' and shot.first_frame_shot_id == ''


def test_source_video_prefers_the_latest_existing_final_file(drama, tmp_path, db_session):
    from datetime import datetime, timedelta
    from models.short_drama import DramaVideoJob, DramaWorkspace
    from services import short_drama_video as video
    api(drama, 'GET')
    workspace = db_session.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    now = datetime.utcnow()
    final_file, preview_file = tmp_path / 'final.mp4', tmp_path / 'preview.mp4'
    final_file.write_bytes(b'final'); preview_file.write_bytes(b'preview')
    db_session.add(DramaVideoJob(workspace_id=workspace.id, shot_id='s1', quality='final', title='', prompt='完整画面',
        duration=5, width=960, height=544, seed=1, mode='turbo', input_mode='text', status='succeeded',
        local_path=str(final_file), finished_at=now))
    db_session.add(DramaVideoJob(workspace_id=workspace.id, shot_id='s1', quality='preview', title='', prompt='完整画面',
        duration=5, width=480, height=272, seed=1, mode='turbo', input_mode='text', status='succeeded',
        local_path=str(preview_file), finished_at=now + timedelta(minutes=5)))
    db_session.commit()
    assert video.source_video(db_session, workspace.id, 's1').local_path == str(final_file)
    final_file.unlink()
    assert video.source_video(db_session, workspace.id, 's1').local_path == str(preview_file)
    preview_file.unlink()
    assert video.source_video(db_session, workspace.id, 's1') is None


@pytest.mark.parametrize('failure', [None, 'upload', 'submit'])
def test_first_lock_extracts_last_frame_uploads_it_and_cleans_the_cluster_file(monkeypatch, tmp_path, failure):
    from services import short_drama_video as video
    from types import SimpleNamespace
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source-video')
    job = SimpleNamespace(id='lock-job', prompt='从这一帧继续向前走', duration=4, width=960, height=544, seed=7,
        mode='turbo', input_mode='first_lock', reference_paths='', first_frame='', last_frame='',
        workspace_id='workspace', first_frame_shot_id='s1')
    monkeypatch.setattr(video, 'source_video', lambda db, workspace_id, shot_id: SimpleNamespace(local_path=str(source)))
    monkeypatch.setattr(video, 'VIDEO_DIR', tmp_path / 'videos')
    calls = []
    from pathlib import Path
    async def command(args, input_data=None):
        calls.append((args, input_data))
        if args[0] == 'ffmpeg':
            Path(args[-1]).write_bytes(b'last-frame')
            return ''
        if args[0] == 'scp' and args[-1].startswith(f'{video.HOST}:'):
            if failure == 'upload':
                raise RuntimeError('upload failed')
            return ''
        if input_data:
            script = input_data.decode()
            assert '--first-frame media_jobs_dev/novel_inputs/lock-job_first.png' in script
            assert '--last-frame' not in script and str(source) not in script
            if failure == 'submit':
                raise RuntimeError('submit failed')
            return json.dumps({'result_file': '/remote/result.json'})
        if args[0] == 'ssh' and args[-1].startswith('cat '):
            return json.dumps({'status': 'succeeded'})
        return ''
    monkeypatch.setattr(video, 'run_command', command)
    if failure:
        with pytest.raises(RuntimeError, match=f'{failure} failed'):
            asyncio.run(video.generate_remote(job))
    else:
        assert asyncio.run(video.generate_remote(job)) == tmp_path / 'videos/lock-job.mp4'
        download_at = next(i for i, (args, _) in enumerate(calls) if args[0] == 'scp' and str(args[-1]).endswith('lock-job.mp4'))
        finished = next(args for args, _ in calls[download_at + 1:] if args[0] == 'ssh' and args[-1].startswith('rm -f --'))
        assert f'{video.PROJECT}/media_jobs_dev/novel_inputs/lock-job_first.png' in finished[-1]
        assert f'{video.PROJECT}/outputs/novel/lock-job.mp4' in finished[-1]
    ffmpeg = next(args for args, _ in calls if args[0] == 'ffmpeg')
    assert ffmpeg == ['ffmpeg', '-y', '-sseof', '-1', '-i', str(source), '-update', '1', str(tmp_path / 'videos/lock-job_first.png')]
    assert not (tmp_path / 'videos/lock-job_first.png').exists()
    cleanup = calls[-1][0]
    assert cleanup[0] == 'ssh'
    assert cleanup[-1] == f'rm -f -- {video.PROJECT}/media_jobs_dev/novel_inputs/lock-job_first.png'


def test_reference_image_limit_is_checked_before_starting_remote_work(drama, monkeypatch, tmp_path, db_session):
    from services import short_drama_video as video
    from models.node import Node
    from models.short_drama import DramaPortrait
    from schemas.short_drama import StoryboardShot
    image = tmp_path / 'portrait.png'
    image.write_bytes(b'image')
    roles = []
    for index in range(9):
        role = Node(id=f'role-{index}', work_id=drama[2].id, type='character', title=f'角色{index}', sort_order=index+10)
        db_session.add(role); db_session.flush()
        db_session.add(DramaPortrait(id=f'p-{index}', work_id=drama[2].id, role_id=role.id, image_path=str(image), prompt='立绘'))
        roles.append(dict(roleId=role.id, portraitId=f'p-{index}'))
    db_session.commit()
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整画面', inputMode='reference', roles=roles).model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    started = []
    monkeypatch.setattr(video, 'start_jobs', started.extend)
    response = api(drama, 'POST', '/videos', {'shot_ids': ['s1']})
    assert response.status_code == 400 and '8' in response.json()['detail']
    assert not started


@pytest.mark.parametrize('entry', ['page', 'agent', 'replace'])
def test_deleting_shot_removes_both_video_qualities_and_keeps_other_shots(drama, monkeypatch, tmp_path, db_session, entry):
    from services import short_drama_video as video
    from schemas.short_drama import StoryboardShot
    from tests.test_storyboard_tool_persistence import repo
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id=s, prompt='完整画面').model_dump() for s in ['s1', 's2']]
    board.pop('portraits'); board.pop('portraitRevision')
    assert api(drama, 'PUT', body=board).status_code == 200
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    async def generate(job):
        path = tmp_path / f'{job.id}.mp4'
        path.write_bytes(b'video')
        return path
    monkeypatch.setattr(video, 'generate_remote', generate)
    paths = {}
    for shot, quality in [('s1', 'preview'), ('s1', 'final'), ('s2', 'final')]:
        job = api(drama, 'POST', '/videos', {'shot_ids': [shot], 'quality': quality}).json()[0]
        asyncio.run(video.run_job(job['id']))
        paths[shot, quality] = tmp_path / f"{job['id']}.mp4"
    posters = {key: path.with_suffix('.jpg') for key, path in paths.items()}
    for poster in posters.values():
        poster.write_bytes(b'frame')
    if entry == 'page':
        board = api(drama, 'GET').json()
        board['shots'] = [s for s in board['shots'] if s['id'] == 's2']
        board.pop('portraits'); board.pop('portraitRevision')
        assert api(drama, 'PUT', body=board).status_code == 200
    else:
        repository = repo(drama, db_session)
        revision = repository.read()['revision']
        if entry == 'agent':
            repository.mutate('delete_shots', dict(expected_revision=revision, shot_ids=['s1']))
        else:
            repository.mutate('replace_storyboard', dict(expected_revision=revision, shots=[dict(title='新镜头', prompt='新画面', duration=5)]))
    assert not paths['s1', 'preview'].exists()
    assert not paths['s1', 'final'].exists()
    assert not posters['s1', 'preview'].exists()
    assert not posters['s1', 'final'].exists()
    remaining = api(drama, 'GET', '/videos').json()
    if entry == 'replace':
        assert not remaining and not paths['s2', 'final'].exists() and not posters['s2', 'final'].exists()
    else:
        assert paths['s2', 'final'].exists() and posters['s2', 'final'].exists()
        assert len(remaining) == 1 and remaining[0]['shot_id'] == 's2'


def test_deleted_video_job_does_not_start_or_leave_late_output(drama, monkeypatch, tmp_path):
    from services import short_drama_video as video
    from models.short_drama import DramaVideoJob
    import database
    board = api(drama, 'GET').json()
    from schemas.short_drama import StoryboardShot
    board['shots'] = [StoryboardShot(id='s1', prompt='画面').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    api(drama, 'PUT', body=board)
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    job = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    output = tmp_path / 'late.mp4'
    async def generate(snapshot):
        with database.SessionLocal() as db:
            db.delete(db.get(DramaVideoJob, snapshot.id))
            db.commit()
        output.write_bytes(b'video')
        return output
    monkeypatch.setattr(video, 'generate_remote', generate)
    asyncio.run(video.run_job(job['id']))
    assert not output.exists()
    async def unexpected(snapshot):
        pytest.fail('已删除的排队任务不应启动')
    monkeypatch.setattr(video, 'generate_remote', unexpected)
    asyncio.run(video.run_job(job['id']))


def test_finished_video_poster_is_the_extracted_first_frame(drama, monkeypatch, tmp_path, db_session):
    import subprocess
    from pathlib import Path
    from models.short_drama import DramaVideoJob
    from schemas.short_drama import StoryboardShot
    from services import short_drama_video as video
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整画面').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    api(drama, 'PUT', body=board)
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    created = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    video_path = tmp_path / f"{created['id']}.mp4"
    video_path.write_bytes(b'video')
    job = db_session.get(DramaVideoJob, created['id'])
    job.status = 'succeeded'
    job.local_path = str(video_path)
    db_session.commit()
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b'jpeg-frame')
        return subprocess.CompletedProcess(args, 0, stderr=b'')
    monkeypatch.setattr(video.subprocess, 'run', fake_run)
    first = api(drama, 'GET', f"/videos/{created['id']}/poster")
    assert first.status_code == 200 and first.content == b'jpeg-frame'
    assert first.headers['content-type'].startswith('image/jpeg')
    assert calls == [['ffmpeg', '-y', '-i', str(video_path), '-frames:v', '1', '-q:v', '3', str(video_path.with_suffix('.jpg'))]]
    second = api(drama, 'GET', f"/videos/{created['id']}/poster")
    assert second.content == b'jpeg-frame' and len(calls) == 1
    job.status = 'running'
    db_session.commit()
    assert api(drama, 'GET', f"/videos/{created['id']}/poster").status_code == 409


def test_replacing_a_finished_video_removes_its_poster(drama, monkeypatch, tmp_path):
    from services import short_drama_video as video
    from schemas.short_drama import StoryboardShot
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整画面').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    api(drama, 'PUT', body=board)
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    async def success(job):
        path = tmp_path / f'{job.id}.mp4'
        path.write_bytes(b'video')
        return path
    monkeypatch.setattr(video, 'generate_remote', success)
    first = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    asyncio.run(video.run_job(first['id']))
    poster = (tmp_path / f"{first['id']}.mp4").with_suffix('.jpg')
    poster.write_bytes(b'frame')
    second = api(drama, 'POST', '/videos', {'shot_ids': ['s1']}).json()[0]
    asyncio.run(video.run_job(second['id']))
    assert not poster.exists()
    assert not (tmp_path / f"{first['id']}.mp4").exists()
    assert (tmp_path / f"{second['id']}.mp4").exists()
