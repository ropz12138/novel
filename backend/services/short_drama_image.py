"""SSH 提交 Qwen 图片一次性作业，下载成图并写回角色立绘。"""
import asyncio
import base64
import json
import logging
from datetime import datetime
from pathlib import Path
import shlex
from types import SimpleNamespace
import database
from models.short_drama import DramaImageJob, DramaPortrait
from services import short_drama_store as store
from services.short_drama_video import HOST, PROJECT, run_command, ssh

IMAGE_DIR = Path(__file__).resolve().parents[2] / 'outputs/short-drama-portraits'
logger = logging.getLogger(__name__)
tasks = set()


async def generate_remote(job):
    remote_prompt = f'media_jobs_dev/novel_inputs/{job.id}.txt'
    remote_output = f'outputs/novel/{job.id}.png'
    args = ['bash', 'media_jobs_dev/generate_image.sh', '--prompt-file', remote_prompt,
            '--width', str(job.width), '--height', str(job.height), '--seed', str(job.seed),
            '--output', remote_output, '--wait']
    encoded = base64.b64encode(job.prompt.encode()).decode()
    script = '\n'.join([
        'set -euo pipefail', f'cd {shlex.quote(PROJECT)}',
        'mkdir -p media_jobs_dev/novel_inputs outputs/novel',
        f'printf %s {shlex.quote(encoded)} | base64 --decode > {shlex.quote(remote_prompt)}',
        shlex.join(args),
    ])
    submission = json.loads(await run_command(ssh(), script.encode()))
    result = json.loads(await run_command(ssh(shlex.join(['cat', '--', submission['result_file']]))))
    if result['status'] != 'succeeded':
        raise RuntimeError(result['error'])
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / f'{job.id}.png'
    await run_command(['scp', '-o', 'BatchMode=yes', '--', f'{HOST}:{PROJECT}/{remote_output}', str(path)])
    await run_command(ssh(shlex.join(['rm', '-f', '--', f'{PROJECT}/{remote_output}', f'{PROJECT}/{remote_prompt}'])))
    return path


async def run_job(job_id):
    with database.SessionLocal() as db:
        job = db.get(DramaImageJob, job_id)
        job.status = 'running'
        db.commit()
        snapshot = SimpleNamespace(**{c.name: getattr(job, c.name) for c in job.__table__.columns})
    try:
        path = await generate_remote(snapshot)
        error = ''
    except Exception as exc:
        logger.exception('short drama image failed job=%s', job_id)
        path, error = None, str(exc)
    with database.SessionLocal() as db:
        job = db.get(DramaImageJob, job_id)
        if path:
            portrait_set = store.lock_portrait_set(db, job.work_id)
            portrait = db.get(DramaPortrait, job.portrait_id) if job.portrait_id else None
            if portrait is not None:
                portrait.image_path = str(path)
                portrait_set.revision += 1
        job.status = 'succeeded' if path else 'failed'
        job.local_path = str(path) if path else ''
        job.error = error
        job.finished_at = datetime.utcnow()
        db.commit()


def start_job(job_id):
    task = asyncio.create_task(run_job(job_id))
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def job_data(job):
    return {key: getattr(job, key) for key in ('id', 'portrait_id', 'status', 'error', 'width', 'height', 'seed', 'created_at', 'finished_at')}
