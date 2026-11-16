import asyncio
from sqlalchemy import text, inspect
from tests.test_short_drama_api import drama
from tests.test_short_drama_persistence import api


def test_preview_dimensions_preserve_aspect_ratio_and_supported_bounds():
    from services.short_drama_video import preview_dimensions
    cases = [((960, 544), (480, 272)), ((544, 960), (272, 480)),
             ((1280, 720), (512, 288)), ((720, 1280), (288, 512)),
             ((1024, 1024), (512, 512)), ((256, 256), (256, 256)),
             ((480, 272), (480, 272)), ((256, 1280), (256, 1280))]
    for original, expected in cases:
        result = preview_dimensions(*original)
        assert result == expected
        assert result[0] * original[1] == result[1] * original[0]
        assert all(256 <= value <= original[i] and value % 16 == 0 for i, value in enumerate(result))


def test_preview_and_final_use_identical_inputs_and_store_independent_results(drama, monkeypatch, tmp_path, db_session):
    from schemas.short_drama import StoryboardShot
    from models.short_drama import DramaPortrait, DramaVideoJob
    from services import short_drama_video as video
    image = tmp_path / 'portrait.png'; image.write_bytes(b'image')
    db_session.add(DramaPortrait(id='p1', work_id=drama[2].id, role_id=drama[4].id, image_path=str(image), prompt='立绘'))
    db_session.commit()
    board = api(drama, 'GET').json()
    prompt = '中文完整视频提示词\n' * 5000
    board['shots'] = [StoryboardShot(id='s1', prompt=prompt, duration=7, seed=123, mode='turbo', inputMode='reference', roles=[dict(roleId=drama[4].id, portraitId='p1')]).model_dump()]
    board.pop('portraits'); board.pop('portraitRevision')
    saved = api(drama, 'PUT', body=board).json()
    started = []
    monkeypatch.setattr(video, 'start_jobs', started.extend)
    preview = api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': 'preview'})
    assert preview.status_code == 200, preview.text
    assert preview.json()[0]['quality'] == 'preview'
    assert (preview.json()[0]['width'], preview.json()[0]['height']) == (480, 272)
    assert api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': 'preview'}).status_code == 409
    assert api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': 'final'}).status_code == 409
    snapshots = []
    async def generate(job):
        snapshots.append(job)
        path = tmp_path / f'{job.id}.mp4'
        path.write_bytes(job.quality.encode())
        return path
    monkeypatch.setattr(video, 'generate_remote', generate)
    asyncio.run(video.run_job(preview.json()[0]['id']))
    final = api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': 'final'})
    assert final.status_code == 200, final.text
    assert final.json()[0]['quality'] == 'final'
    assert (final.json()[0]['width'], final.json()[0]['height']) == (960, 544)
    assert api(drama, 'GET').json() == saved
    asyncio.run(video.run_job(final.json()[0]['id']))
    assert len(started) == 2 and started[0] != started[1]
    for field in ('prompt', 'duration', 'seed', 'mode', 'input_mode', 'reference_paths'):
        assert getattr(snapshots[0], field) == getattr(snapshots[1], field)
    assert snapshots[0].prompt == prompt
    for job_id, quality in zip(started, ['preview', 'final']):
        assert api(drama, 'GET', f'/videos/{job_id}/file').content == quality.encode()
        row = db_session.get(DramaVideoJob, job_id)
        db_session.refresh(row)
        assert row.status == 'succeeded' and row.quality == quality
    rows = api(drama, 'GET', '/videos').json()
    assert {row['quality'] for row in rows} == {'preview', 'final'}
    assert all(row['fps'] == 24 for row in rows)
    assert api(drama, 'POST', '/videos', {'shot_ids': ['s1'], 'quality': 'unknown'}).status_code == 422


def test_startup_migrates_existing_video_jobs_to_final_without_changing_results(drama, db_session):
    from models.short_drama import DramaVideoJob, DramaWorkspace
    from services.short_drama_migration import upgrade_video_quality
    from services.short_drama_video import job_data
    api(drama, 'GET')
    board = db_session.query(DramaWorkspace).one()
    job = DramaVideoJob(workspace_id=board.id, shot_id='old-shot', title='已有视频', prompt='完整提示词', duration=5,
        width=960, height=544, seed=42, mode='turbo', input_mode='text', status='succeeded', local_path='/keep/old.mp4')
    db_session.add(job); db_session.commit(); job_id = job.id; db_session.commit()
    with db_session.bind.begin() as connection:
        connection.execute(text('ALTER TABLE drama_video_jobs DROP COLUMN quality'))
    upgrade_video_quality(db_session.bind)
    upgrade_video_quality(db_session.bind)
    db_session.expire_all()
    data = job_data(db_session.get(DramaVideoJob, job_id))
    assert data['quality'] == 'final' and data['width'] == 960 and data['height'] == 544
    assert db_session.get(DramaVideoJob, job_id).local_path == '/keep/old.mp4'
    columns = inspect(db_session.bind).get_columns('drama_video_jobs')
    assert all('JSON' not in str(column['type']) for column in columns)
