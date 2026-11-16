#!/usr/bin/env python3
"""One-shot image/video GPU jobs. Submission uses only Python's standard library."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_PROJECT = '/data/home/tg100044/dfcs-bak/dspawagent/liyicheng/Video'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-request', type=Path, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='kind')
    for kind in ('image', 'video'):
        p = sub.add_parser(kind)
        p.add_argument('--project', type=Path, default=Path(os.environ.get('H3_PROJECT', DEFAULT_PROJECT)))
        prompt = p.add_mutually_exclusive_group(required=True)
        prompt.add_argument('--prompt')
        prompt.add_argument('--prompt-file', type=Path)
        p.add_argument('--output', required=True)
        p.add_argument('--reference-images', nargs='+', default=[])
        p.add_argument('--width', type=int, default=1024 if kind == 'image' else 960)
        p.add_argument('--height', type=int, default=1024 if kind == 'image' else 544)
        p.add_argument('--seed', type=int, default=42)
        p.add_argument('--partition', default='tx4090')
        p.add_argument('--time-limit', default='04:00:00')
        p.add_argument('--wait', action='store_true', help='等待 Slurm 作业结束，日志写入任务目录')
        p.add_argument('--dry-run', action='store_true', help='校验参数并显示计划，不提交 GPU 作业')
        if kind == 'image':
            p.add_argument('--model-dir', type=Path)
            p.add_argument('--image-model', choices=('qwen', 'minimax-h3-w4a8', 'minimax-h3-int8'), default='qwen')
        else:
            p.add_argument('--duration', type=float, default=5)
            p.add_argument('--first-frame')
            p.add_argument('--last-frame')
            p.add_argument('--mode', choices=('turbo', 'base'), default='turbo')
            p.add_argument('--steps', type=int)
    args = parser.parse_args(argv)
    if not args.run_request and not args.kind:
        parser.error('请选择 image 或 video')
    return args


def project_path(root, value, *, must_exist=False):
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'路径必须位于项目目录内：{path}')
    if must_exist and not path.is_file():
        raise FileNotFoundError(path)
    return path


def prepare_request(args):
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    if args.prompt_file:
        source = args.prompt_file.expanduser()
        prompt = (source if source.is_absolute() else root / source).read_text(encoding='utf-8')
    else:
        prompt = args.prompt
    if not prompt.strip():
        raise ValueError('提示词不能为空')
    if args.seed < 0:
        raise ValueError('seed 必须大于等于 0')
    if args.width % 16 or args.height % 16 or min(args.width, args.height) < 256:
        raise ValueError('宽高必须是至少 256 的 16 倍数')
    out = project_path(root, args.output)
    suffix = '.png' if args.kind == 'image' else '.mp4'
    if out.suffix.lower() != suffix:
        raise ValueError(f'输出文件需使用 {suffix} 后缀')
    if out.exists():
        raise FileExistsError(f'输出文件已存在：{out}')
    refs = [str(project_path(root, p, must_exist=True)) for p in args.reference_images]
    limit = (16 if args.image_model != 'qwen' else 10) if args.kind == 'image' else 8
    if len(refs) > limit:
        raise ValueError(f'最多支持 {limit} 张参考图')
    request = dict(kind=args.kind, project=str(root), prompt=prompt, output_path=str(out), reference_images=refs, width=args.width, height=args.height, seed=args.seed)
    if args.kind == 'image':
        minimax = args.image_model != 'qwen'
        model_dirs = {'qwen': 'Qwen-Image-2.1-Turbo', 'minimax-h3-w4a8': 'MiniMax-H3-Image-W4A8', 'minimax-h3-int8': 'MiniMax-H3-Image-INT8'}
        model = args.model_dir or root / 'models' / model_dirs[args.image_model]
        model = model.expanduser()
        model = (model if model.is_absolute() else root / model).resolve()
        if minimax:
            unet_name = 'minimax_h3_image_pruned_int8_convrot.safetensors' if args.image_model == 'minimax-h3-int8' else 'minimax_h3_image_pruned_w4a8.safetensors'
            vae_dir = root / 'models/MiniMax-H3-Image-W4A8/vae' if args.image_model == 'minimax-h3-int8' else model / 'vae'
            required = [model / 'diffusion_models' / unet_name,
                        vae_dir / 'minimax_h3_image_vae_fp16.safetensors',
                        root / 'models/Comfy-Org-MiniMax-H3/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors']
            for path in required:
                if not path.is_file():
                    raise FileNotFoundError(path)
            request.update(unet_name=unet_name, vae_dir=str(vae_dir))
        else:
            config = json.loads((model / 'model_index.json').read_text())
            if config.get('_class_name') != 'QwenImage21Pipeline' or len(config.get('sample_sigmas', [])) != 8:
                raise ValueError('需要带官方 8 步 sample_sigmas 的 Qwen-Image-2.1-Turbo 模型')
        request['model_dir'] = str(model)
        request['image_model'] = args.image_model
    else:
        if max(args.width, args.height) > 1280:
            raise ValueError('H3 当前服务工作流的宽高上限为 1280')
        if not 1 <= args.duration <= 15:
            raise ValueError('视频时长必须在 1 到 15 秒之间')
        if refs and (args.first_frame or args.last_frame):
            raise ValueError('H3 当前工作流不能同时使用参考图和首尾帧')
        turbo = args.mode == 'turbo'
        steps = args.steps if args.steps is not None else (8 if turbo else 20)
        if not 1 <= steps <= 50 or (turbo and steps != 8):
            raise ValueError('Turbo 需使用 8 步；基础模式支持 1 到 50 步')
        request.update(duration=args.duration, turbo=turbo, steps=steps)
        for key in ('first_frame', 'last_frame'):
            value = getattr(args, key)
            request[key] = str(project_path(root, value, must_exist=True)) if value else None
    return request


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def submit(args, request):
    root = Path(request['project'])
    minimax = request.get('image_model') in ('minimax-h3-w4a8', 'minimax-h3-int8')
    env_name = ('.venv-h3-image' if minimax else '.venv-image') if request['kind'] == 'image' else '.venv-comfy'
    python = root / env_name / 'bin/python'
    if not python.is_file():
        raise FileNotFoundError(f'缺少推理环境：{python}；请先执行 README 中的环境安装命令')
    task_dir = root / 'media_jobs_dev/runs' / (datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
    task_dir.mkdir(parents=True)
    request_file = task_dir / 'request.json'
    request['request_file'] = str(request_file)
    save_json(request_file, request)
    runner = Path(__file__).resolve()
    log = task_dir / 'slurm-%j.log'
    job_name = ('h3_image_once' if minimax else 'qwen_image_once') if args.kind == 'image' else 'h3_video_once'
    command = ['sbatch', '--parsable', '--job-name=' + job_name, '--partition=' + args.partition, '--gres=gpu:1', '--ntasks=1', '--cpus-per-task=10', '--mem=90000M', '--time=' + args.time_limit, '--chdir=' + str(root), '--output=' + str(log)]
    if args.wait:
        command.append('--wait')
    command += ['--wrap', 'exec ' + shlex.join([str(python), str(runner), '--run-request', str(request_file)])]
    failure = None
    try:
        result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE)
        stdout = result.stdout
    except subprocess.CalledProcessError as exc:
        result_file = request_file.with_suffix('.result.json')
        if not args.wait or not result_file.is_file():
            raise
        failure = json.loads(result_file.read_text())
        stdout = exc.stdout
    job_id = stdout.strip().split(';')[0]
    submission = dict(slurm_job_id=job_id, request_file=str(request_file), result_file=str(request_file.with_suffix('.result.json')), log_file=str(log).replace('%j', job_id))
    if failure is not None:
        submission.update(status=failure['status'], error=failure['error'])
    save_json(task_dir / 'submission.json', submission)
    return submission


def run_image(request):
    if request.get('image_model') in ('minimax-h3-w4a8', 'minimax-h3-int8'):
        from h3_image import run_image as run_minimax
        return run_minimax(request)
    # Local weights only: downloads and dependency installation are separate setup steps.
    import torch
    from diffusers import QwenImage21Pipeline
    from PIL import Image

    if not torch.cuda.is_available():
        raise RuntimeError('当前作业没有可用 CUDA GPU，请通过 Slurm 提交')
    started = time.perf_counter()
    pipe = QwenImage21Pipeline.from_pretrained(request['model_dir'], dtype=torch.bfloat16, local_files_only=True)
    if len(pipe.config.sample_sigmas) != 8:
        raise ValueError('加载后的模型缺少官方 8 步采样配置')
    # Each component fits individually; the full BF16 pipeline exceeds one 24GB GPU.
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_tiling()
    images = []
    for path in request['reference_images']:
        with Image.open(path) as source:
            images.append(source.convert('RGBA'))
    loaded_seconds = time.perf_counter() - started
    inference_start = time.perf_counter()
    result = pipe(prompt=request['prompt'], image=images or None, width=request['width'], height=request['height'], use_kv_cache=True, generator=torch.Generator('cpu').manual_seed(request['seed']))
    inference_seconds = time.perf_counter() - inference_start
    out = Path(request['output_path'])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against another job finishing at the same path.
    with out.open('xb') as f:
        result.images[0].save(f, format='PNG')
    return dict(output_path=str(out), model_load_seconds=loaded_seconds, inference_seconds=inference_seconds, steps=8, actual_size=list(result.images[0].size), gpu=torch.cuda.get_device_name(0), peak_vram_bytes=torch.cuda.max_memory_allocated(0))


def load_video_service(root):
    spec = importlib.util.spec_from_file_location('h3_one_shot_service', root / 'h3_video_service/service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


def wait_for_comfy(process, base, timeout=600):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'ComfyUI 提前退出，退出码 {process.returncode}；请检查 comfy.log')
        try:
            with opener.open(base + '/system_stats', timeout=3) as res:
                json.load(res)
            return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    raise TimeoutError('ComfyUI 启动超过 600 秒；请检查 comfy.log')


def run_video(request):
    root = Path(request['project'])
    task_dir = Path(request.get('request_file', root / 'media_jobs_dev/runs/local/request.json')).parent
    task_dir.mkdir(parents=True, exist_ok=True)
    os.environ['H3_PROJECT'] = str(root)
    os.environ['H3_STATE_DIR'] = str(task_dir / 'state')
    # A dynamic local port prevents clashes with any existing service on the node.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    os.environ['H3_COMFY_PORT'] = str(port)
    service = load_video_service(root)
    params = service.validate(request)
    service.INP = task_dir / 'inputs'
    service.INP.mkdir(parents=True, exist_ok=True)
    service.OUT = task_dir / 'outputs'
    service.OUT.mkdir(parents=True, exist_ok=True)
    with (task_dir / 'comfy.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-u', str(root / 'ComfyUI/main.py'), '--listen', '127.0.0.1', '--port', str(port), '--disable-auto-launch', '--lowvram', '--input-directory', str(service.INP), '--output-directory', str(service.OUT), '--user-directory', str(root / 'ComfyUI/user')], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        try:
            startup = time.perf_counter()
            wait_for_comfy(process, 'http://127.0.0.1:' + str(port))
            ready_seconds = time.perf_counter() - startup
            jid = 'once_' + uuid.uuid4().hex[:16]
            job = dict(job_id=jid, status='running', params=params)
            service.jobs[jid] = job
            result = service.render(job)
            result.update(comfy_ready_seconds=ready_seconds, job_id=jid, prompt_id=job['prompt_id'])
            return result
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            shutil.rmtree(service.INP)
            shutil.rmtree(service.OUT)


def execute(request):
    started = time.perf_counter()
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'DIFFUSERS_OFFLINE'):
        os.environ[name] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    path = Path(request['request_file']).with_suffix('.result.json')
    metadata = dict(kind=request['kind'], status='running', node=socket.gethostname(), slurm_job_id=os.environ.get('SLURM_JOB_ID'), started_at=datetime.now(timezone.utc).isoformat())
    save_json(path, metadata)
    try:
        out = Path(request['output_path'])
        if out.exists():
            raise FileExistsError(out)
        result = run_image(request) if request['kind'] == 'image' else run_video(request)
    except Exception as exc:
        metadata.update(status='failed', error=f'{type(exc).__name__}: {exc}', total_seconds=time.perf_counter()-started, finished_at=datetime.now(timezone.utc).isoformat())
        save_json(path, metadata)
        raise
    metadata.update(status='succeeded', total_seconds=time.perf_counter()-started, finished_at=datetime.now(timezone.utc).isoformat(), result=result)
    save_json(path, metadata)
    return metadata


def main():
    args = parse_args()
    if args.run_request:
        request = json.loads(args.run_request.read_text(encoding='utf-8'))
        result = execute(request)
    else:
        request = prepare_request(args)
        result = dict(dry_run=True, request=request) if args.dry_run else submit(args, request)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if result.get('status') == 'failed':
        sys.exit(1)


if __name__ == '__main__':
    main()
