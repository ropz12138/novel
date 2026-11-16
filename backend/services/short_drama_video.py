"""通过 SSH 调用集群一次性脚本，视频任务与分镜生成相互独立。"""
import asyncio
import base64
import json
import logging
import os
import subprocess
from math import gcd
from datetime import datetime
from pathlib import Path
import shlex
import database
from models.short_drama import DramaVideoJob

HOST = os.environ.get('NOVEL_VIDEO_SSH_HOST', 'hzwCloud44')
PROJECT = os.environ.get('NOVEL_VIDEO_PROJECT', '/data/home/tg100044/dfcs-bak/dspawagent/liyicheng/Video')
VIDEO_DIR = Path(__file__).resolve().parents[2] / 'outputs/short-drama-videos'
logger = logging.getLogger(__name__)
tasks = set()


def preview_dimensions(width, height):
    """按原比例选取约半尺寸的合法画幅，短边至少 256，不放大。"""
    divisor = gcd(width // 16, height // 16)
    base_width, base_height = width // divisor, height // divisor
    short_side = min(base_width, base_height)
    factor = max(divisor // 2, (256 + short_side - 1) // short_side)
    return base_width * factor, base_height * factor


async def run_command(args, input_data=None):
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if input_data else asyncio.subprocess.DEVNULL,
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate(input_data)
    if process.returncode:
        raise RuntimeError(f'{args[0]} 执行失败：{stderr.decode(errors="replace")}')
    return stdout.decode()


def ssh(command=None):
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=30', HOST]
    return args + ([command] if command else ['bash -s'])


def generation_mode(shot):
    """由已选立绘和首帧来源决定生成方式，不读取手工选择的输入模式。"""
    has_source = bool(shot.get('firstFrameShotId'))
    has_reference = any(role.get('portraitId') for role in shot.get('roles') or [])
    if has_source and has_reference:
        return 'conflict'
    if has_source:
        return 'first_lock'
    if has_reference:
        return 'reference'
    return 'text'


def source_video(db, workspace_id, shot_id):
    """取来源镜头仍在本地的成片。成片优先于预览，同一质量取最近完成的文件。"""
    rows = db.query(DramaVideoJob).filter(
        DramaVideoJob.workspace_id == workspace_id, DramaVideoJob.shot_id == shot_id,
        DramaVideoJob.status == 'succeeded', DramaVideoJob.local_path != '').all()
    available = [row for row in rows if Path(row.local_path).is_file()]
    finals = [row for row in available if row.quality == 'final']
    chosen = finals or available
    if not chosen:
        return None
    return max(chosen, key=lambda row: row.finished_at or row.created_at)


def discard_video_file(path):
    file = Path(path)
    file.unlink(missing_ok=True)
    file.with_suffix('.jpg').unlink(missing_ok=True)


def ensure_first_frame(video_path):
    video = Path(video_path)
    image = video.with_suffix('.jpg')
    if image.is_file() and image.stat().st_size > 0 and image.stat().st_mtime >= video.stat().st_mtime:
        return image
    completed = subprocess.run(
        ['ffmpeg', '-y', '-i', str(video), '-frames:v', '1', '-q:v', '3', str(image)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if completed.returncode or not image.is_file() or image.stat().st_size == 0:
        detail = completed.stderr.decode(errors='replace').strip()
        raise RuntimeError(detail or '未能提取视频首帧')
    return image


async def extract_last_frame(video_path, image_path):
    await run_command(['ffmpeg', '-y', '-sseof', '-1', '-i', str(video_path), '-update', '1', str(image_path)])
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise RuntimeError('未能从来源视频提取最后一帧')


async def generate_remote(job):
    remote_prompt = f'media_jobs_dev/novel_inputs/{job.id}.txt'
    remote_output = f'outputs/novel/{job.id}.mp4'
    args = ['bash', 'media_jobs_dev/generate_video.sh', '--prompt-file', remote_prompt,
            '--duration', str(job.duration), '--width', str(job.width), '--height', str(job.height),
            '--seed', str(job.seed), '--mode', job.mode, '--steps', '8' if job.mode == 'turbo' else '20',
            '--output', remote_output, '--wait']
    reference_dir = f'media_jobs_dev/novel_inputs/{job.id}_refs'
    references = []
    if job.input_mode == 'reference':
        references = [Path(path) for path in job.reference_paths.splitlines()]
        args += ['--reference-images', *[f'{reference_dir}/{index}{path.suffix.lower()}' for index, path in enumerate(references, 1)]]
    frame_remote = None
    frame_local = None
    try:
        if job.input_mode == 'first_lock':
            with database.SessionLocal() as db:
                source = source_video(db, job.workspace_id, job.first_frame_shot_id)
            if source is None:
                raise RuntimeError('来源镜头没有可使用的成片')
            frame_local = VIDEO_DIR / f'{job.id}_first.png'
            VIDEO_DIR.mkdir(parents=True, exist_ok=True)
            await extract_last_frame(source.local_path, frame_local)
            frame_remote = f'media_jobs_dev/novel_inputs/{job.id}_first.png'
            args += ['--first-frame', frame_remote]
        encoded = base64.b64encode(job.prompt.encode()).decode()
        script = '\n'.join([
            'set -euo pipefail', f'cd {shlex.quote(PROJECT)}',
            'mkdir -p media_jobs_dev/novel_inputs outputs/novel',
            f'printf %s {shlex.quote(encoded)} | base64 --decode > {shlex.quote(remote_prompt)}',
            shlex.join(args),
        ])
        if frame_remote:
            await run_command(ssh(shlex.join(['mkdir', '-p', '--', f'{PROJECT}/media_jobs_dev/novel_inputs'])))
            await run_command(['scp', '-o', 'BatchMode=yes', '--', str(frame_local), f'{HOST}:{PROJECT}/{frame_remote}'])
        if references:
            await run_command(ssh(shlex.join(['mkdir', '-p', '--', f'{PROJECT}/{reference_dir}'])))
            for index, path in enumerate(references, 1):
                await run_command(['scp', '-o', 'BatchMode=yes', '--', str(path),
                    f'{HOST}:{PROJECT}/{reference_dir}/{index}{path.suffix.lower()}'])
        submission = json.loads(await run_command(ssh(), script.encode()))
        result = json.loads(await run_command(ssh(shlex.join(['cat', '--', submission['result_file']]))))
        if result['status'] != 'succeeded':
            raise RuntimeError(result.get('error') or '集群视频生成失败')
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        local_path = VIDEO_DIR / f'{job.id}.mp4'
        await run_command(['scp', '-o', 'BatchMode=yes', '--', f'{HOST}:{PROJECT}/{remote_output}', str(local_path)])
        finished = [f'{PROJECT}/{remote_output}', f'{PROJECT}/{remote_prompt}']
        if frame_remote:
            finished.append(f'{PROJECT}/{frame_remote}')
        await run_command(ssh(shlex.join(['rm', '-f', '--', *finished])))
        return local_path
    finally:
        if frame_remote:
            await run_command(ssh(shlex.join(['rm', '-f', '--', f'{PROJECT}/{frame_remote}'])))
        if frame_local is not None:
            frame_local.unlink(missing_ok=True)
        if references:
            await run_command(ssh(shlex.join(['rm', '-rf', '--', f'{PROJECT}/{reference_dir}'])))


async def run_job(job_id):
    with database.SessionLocal() as db:
        job = db.get(DramaVideoJob, job_id)
        if job is None:
            return
        job.status = 'running'
        db.commit()
        # 准备完整不可变输入，生成期间释放数据库连接。
        from types import SimpleNamespace
        snapshot = SimpleNamespace(**{c.name: getattr(job, c.name) for c in job.__table__.columns})
    try:
        path = await generate_remote(snapshot)
        error = ''
    except Exception as exc:
        logger.exception('short drama video failed job=%s', job_id)
        path, error = None, str(exc)
    with database.SessionLocal() as db:
        job = db.get(DramaVideoJob, job_id)
        if job is None:
            if path:
                discard_video_file(path)
            return
        if path:
            previous = db.query(DramaVideoJob).filter(
                DramaVideoJob.workspace_id == job.workspace_id, DramaVideoJob.shot_id == job.shot_id,
                DramaVideoJob.quality == job.quality, DramaVideoJob.status == 'succeeded',
                DramaVideoJob.id != job.id).all()
            for old in previous:
                if old.local_path:
                    discard_video_file(old.local_path)
                db.delete(old)
        job.status = 'succeeded' if path else 'failed'
        job.local_path = str(path) if path else ''
        job.error = error
        job.finished_at = datetime.utcnow()
        db.commit()


def start_jobs(ids):
    for job_id in ids:
        task = asyncio.create_task(run_job(job_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def job_data(job):
    return {**{key: getattr(job, key) for key in ('id', 'shot_id', 'title', 'quality', 'width', 'height', 'duration', 'mode', 'seed', 'status', 'error', 'created_at', 'finished_at')}, 'fps': 24}
