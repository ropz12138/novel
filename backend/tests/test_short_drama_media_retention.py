import asyncio
import json
from types import SimpleNamespace
import pytest
from tests.test_short_drama_api import drama
from tests.test_short_drama_persistence import api


@pytest.mark.parametrize('kind', ['image', 'video'])
@pytest.mark.parametrize('download_fails', [False, True])
def test_remote_result_is_deleted_only_after_successful_download(monkeypatch, tmp_path, kind, download_fails):
    from services import short_drama_image, short_drama_video
    module = short_drama_image if kind == 'image' else short_drama_video
    suffix = '.png' if kind == 'image' else '.mp4'
    job = SimpleNamespace(id='download-job', prompt='完整提示词', width=768, height=1024, seed=42,
        duration=5, mode='turbo', input_mode='text', reference_paths='', first_frame='', last_frame='')
    monkeypatch.setattr(module, 'IMAGE_DIR' if kind == 'image' else 'VIDEO_DIR', tmp_path)
    calls = []
    async def command(args, input_data=None):
        calls.append(args)
        if input_data:
            return json.dumps({'result_file': '/remote/result.json'})
        if args[0] == 'scp':
            if download_fails:
                raise RuntimeError('download failed')
            from pathlib import Path
            Path(args[-1]).write_bytes(b'downloaded-result')
            return ''
        if args[-1].startswith('rm '):
            assert (tmp_path / ('download-job' + suffix)).read_bytes() == b'downloaded-result'
            return ''
        return json.dumps({'status': 'succeeded'})
    monkeypatch.setattr(module, 'run_command', command)
    if download_fails:
        with pytest.raises(RuntimeError, match='download failed'):
            asyncio.run(module.generate_remote(job))
        assert not any(args[-1].startswith('rm ') for args in calls)
    else:
        path = asyncio.run(module.generate_remote(job))
        assert path.read_bytes() == b'downloaded-result'
        assert calls[-1][-1] == f'rm -f -- {module.PROJECT}/outputs/novel/download-job{suffix} {module.PROJECT}/media_jobs_dev/novel_inputs/download-job.txt'


@pytest.mark.parametrize('quality', ['preview', 'final'])
def test_new_success_replaces_only_same_shot_and_quality_and_failure_preserves_old(drama, monkeypatch, tmp_path, db_session, quality):
    from models.short_drama import DramaVideoJob, DramaWorkspace
    from schemas.short_drama import StoryboardShot
    from services import short_drama_video as video
    board = api(drama, 'GET').json()
    board['shots'] = [StoryboardShot(id='s1', prompt='完整视频提示词').model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    api(drama, 'PUT', body=board)
    workspace = db_session.query(DramaWorkspace).one()
    old_ids, old_paths, keep_paths = [], [], []
    for name, shot_id, item_quality in [('old1', 's1', quality), ('old2', 's1', quality),
        ('other-quality', 's1', 'final' if quality == 'preview' else 'preview'), ('other-shot', 's2', quality)]:
        path = tmp_path / f'{name}.mp4'; path.write_bytes(name.encode())
        row = DramaVideoJob(workspace_id=workspace.id, shot_id=shot_id, title=name, prompt='旧提示词', duration=5,
            width=960, height=544, seed=42, mode='turbo', input_mode='text', quality=item_quality,
            status='succeeded', local_path=str(path))
        db_session.add(row); db_session.flush()
        if name.startswith('old'):
            old_ids.append(row.id); old_paths.append(path)
        else:
            keep_paths.append(path)
    db_session.commit()
    monkeypatch.setattr(video, 'start_jobs', lambda ids: None)
    async def fail(job):
        raise RuntimeError('生成失败')
    monkeypatch.setattr(video, 'generate_remote', fail)
    failed = api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': quality}).json()[0]
    asyncio.run(video.run_job(failed['id']))
    assert all(path.is_file() for path in old_paths + keep_paths)
    for job_id in old_ids:
        assert api(drama, 'GET', f'/videos/{job_id}/file').status_code == 200
    async def success(job):
        assert all(path.is_file() for path in old_paths + keep_paths)
        path = tmp_path / f'{job.id}.mp4'; path.write_bytes(b'new-video')
        return path
    monkeypatch.setattr(video, 'generate_remote', success)
    fresh = api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': quality}).json()[0]
    asyncio.run(video.run_job(fresh['id']))
    assert not any(path.exists() for path in old_paths)
    assert all(path.is_file() for path in keep_paths)
    assert api(drama, 'GET', f"/videos/{fresh['id']}/file").content == b'new-video'
    for job_id in old_ids:
        assert api(drama, 'GET', f'/videos/{job_id}/file').status_code == 404
    rows = api(drama, 'GET', '/videos').json()
    matching = [row for row in rows if row['shot_id'] == 's1' and row['quality'] == quality and row['status'] == 'succeeded']
    assert [row['id'] for row in matching] == [fresh['id']]
    assert any(row['id'] == failed['id'] and row['status'] == 'failed' for row in rows)
