"""One-shot MiniMax-H3-Image W4A8/INT8 using an isolated native ComfyUI workflow."""
import json
import math
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from media_job import wait_for_comfy


def build_workflow(request):
    width, height = request['width'], request['height']
    scale = max(1, math.sqrt(2048 ** 2 / (width * height)))
    canvas_width = math.ceil(width * scale / 32) * 32
    canvas_height = math.ceil(height * scale / 32) * 32
    graph = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': request['unet_name'], 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'type': 'minimax', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_image_vae_fp16.safetensors'}},
        '4': {'class_type': 'MiniMaxH3ImageConditioning', 'inputs': {'clip': ['2', 0], 'vae': ['3', 0], 'prompt': request['prompt'], 'width': canvas_width, 'height': canvas_height}},
        '5': {'class_type': 'KSampler', 'inputs': {'model': ['10', 0], 'positive': ['4', 0], 'negative': ['6', 0], 'latent_image': ['4', 1], 'seed': request['seed'], 'steps': 6, 'cfg': 1, 'sampler_name': 'euler', 'scheduler': 'simple', 'denoise': 1}},
        '6': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['4', 0]}},
        '7': {'class_type': 'VAEDecode', 'inputs': {'samples': ['5', 0], 'vae': ['3', 0]}},
        '8': {'class_type': 'ImageScale', 'inputs': {'image': ['7', 0], 'upscale_method': 'lanczos', 'width': width, 'height': height, 'crop': 'disabled'}},
        '9': {'class_type': 'SaveImage', 'inputs': {'images': ['8', 0], 'filename_prefix': 'portrait'}},
        '10': {'class_type': 'ModelAttentionBackend', 'inputs': {'model': ['1', 0], 'attention': 'pytorch attention'}},
    }
    for i, path in enumerate(request['reference_images'], 1):
        node_id = f'ref_{i}'
        graph[node_id] = {'class_type': 'LoadImage', 'inputs': {'image': f'reference_{i}{Path(path).suffix}'}}
        graph['4']['inputs'][f'images.image_{i}'] = [node_id, 0]
    return graph


def wait_for_image(opener, base, prompt_id, process):
    while True:
        if process.poll() is not None:
            raise RuntimeError(f'ComfyUI 提前退出，退出码 {process.returncode}；请检查 comfy-image.log')
        with opener.open(base + '/history/' + prompt_id, timeout=30) as response:
            history = json.loads(response.read())
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry['status']
            if status['status_str'] == 'error':
                raise RuntimeError('ComfyUI 图片生成失败：' + json.dumps(status['messages'], ensure_ascii=False))
            if status['completed']:
                return entry['outputs']['9']['images'][0]
        time.sleep(1)


def run_image(request):
    root = Path(request['project'])
    task_dir = Path(request['request_file']).parent
    task_dir.mkdir(parents=True, exist_ok=True)
    config = task_dir / 'h3-model-paths.yaml'
    # JSON is a YAML subset. Only model search paths are configured here.
    config.write_text(json.dumps({'h3_image_dev': {
        'base_path': request['model_dir'], 'diffusion_models': 'diffusion_models'},
        'h3_image_vae': {'vae': request['vae_dir']},
        'h3_encoder': {'base_path': str(root / 'models/Comfy-Org-MiniMax-H3'), 'text_encoders': 'text_encoders'}}, indent=2))
    graph = build_workflow(request)
    (task_dir / 'workflow.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='image-', dir=task_dir) as directory:
        temporary = Path(directory)
        inputs, outputs, user = (temporary / name for name in ('inputs', 'outputs', 'user'))
        for path in (inputs, outputs, user):
            path.mkdir()
        for i, path in enumerate(request['reference_images'], 1):
            shutil.copyfile(path, inputs / f'reference_{i}{Path(path).suffix}')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        command = [sys.executable, '-u', str(root / 'ComfyUI-h3-image-dev/main.py'),
                   '--listen', '127.0.0.1', '--port', str(port), '--disable-auto-launch',
                   '--enable-triton-backend', '--offline', '--disable-all-custom-nodes',
                   '--extra-model-paths-config', str(config), '--input-directory', str(inputs),
                   '--output-directory', str(outputs), '--user-directory', str(user)]
        with (task_dir / 'comfy-image.log').open('w') as log:
            started = time.perf_counter()
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_for_comfy(process, base)
                ready_seconds = time.perf_counter() - started
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                payload = json.dumps({'prompt': graph}, ensure_ascii=False).encode()
                inference_start = time.perf_counter()
                with opener.open(urllib.request.Request(base + '/prompt', data=payload, headers={'Content-Type': 'application/json'}), timeout=30) as response:
                    prompt_id = json.loads(response.read())['prompt_id']
                image = wait_for_image(opener, base, prompt_id, process)
                source = outputs / image['subfolder'] / image['filename']
                out = Path(request['output_path'])
                out.parent.mkdir(parents=True, exist_ok=True)
                with source.open('rb') as input_file, out.open('xb') as output_file:
                    shutil.copyfileobj(input_file, output_file)
                return dict(output_path=str(out), model=request['unet_name'], steps=6,
                            comfy_ready_seconds=ready_seconds, inference_seconds=time.perf_counter() - inference_start,
                            canvas_size=[graph['4']['inputs']['width'], graph['4']['inputs']['height']],
                            actual_size=[request['width'], request['height']], prompt_id=prompt_id)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
