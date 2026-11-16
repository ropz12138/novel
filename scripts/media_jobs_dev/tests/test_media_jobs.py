import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
import types
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / 'media_job.py'
spec = importlib.util.spec_from_file_location('media_job', MODULE)
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        model = self.root / 'models/Qwen-Image-2.1-Turbo'
        model.mkdir(parents=True)
        (model / 'model_index.json').write_text(json.dumps({'_class_name': 'QwenImage21Pipeline', 'sample_sigmas': [1, .9, .8, .7, .6, .5, .4, .3]}))
        self.model = model
        python = self.root / ".venv-image/bin/python"
        python.parent.mkdir(parents=True)
        python.touch()

    def parse(self, kind='image', *extra):
        return media.parse_args([kind, '--project', str(self.root), '--prompt', '测试完整提示词', '--output', 'outputs/test.' + ('png' if kind == 'image' else 'mp4'), *extra])

    def test_prompt_file_preserves_full_text_and_newlines(self):
        prompt = '角色要求\n' + '完整内容' * 20000 + '\n'
        path = self.root / 'prompt.txt'
        path.write_text(prompt)
        args = media.parse_args(['image', '--project', str(self.root), '--prompt-file', str(path), '--output', 'outputs/test.png'])
        request = media.prepare_request(args)
        self.assertEqual(request['prompt'], prompt)

    def test_rejects_overwriting_and_paths_outside_project(self):
        for name in ('../escape.png', '/tmp/outside.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                media.prepare_request(self.parse('image', '--output', name))
        out = self.root / 'outputs/test.png'
        out.parent.mkdir()
        out.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            media.prepare_request(self.parse())
        self.assertEqual(out.read_bytes(), b'existing')

    def test_image_reference_order_and_limit(self):
        paths = []
        for i in range(11):
            p = self.root / f'ref{i}.png'
            p.touch()
            paths.append(str(p))
        request = media.prepare_request(self.parse('image', '--reference-images', *paths[:2]))
        self.assertEqual(request['reference_images'], paths[:2])
        with self.assertRaises(ValueError):
            media.prepare_request(self.parse('image', '--reference-images', *paths))

    def test_video_rejects_reference_and_first_frame_combination(self):
        p = self.root / 'input.png'
        p.touch()
        with self.assertRaises(ValueError):
            media.prepare_request(self.parse('video', '--reference-images', str(p), '--first-frame', str(p)))

    def test_invalid_dimensions_and_turbo_steps_rejected_before_submission(self):
        with self.assertRaises(ValueError):
            media.prepare_request(self.parse('image', '--width', '1001'))
        with self.assertRaises(ValueError):
            media.prepare_request(self.parse('video', '--steps', '20'))

    def test_submit_snapshots_prompt_and_uses_exact_python_without_shell_injection(self):
        args = self.parse('image', '--prompt', '原文 $(touch bad); `false`\n第二行')
        request = media.prepare_request(args)
        with patch.object(media.subprocess, 'run', return_value=Mock(stdout='12345;cluster\n')) as run:
            result = media.submit(args, request)
        command = run.call_args.args[0]
        self.assertEqual(command[0], 'sbatch')
        self.assertEqual(result['slurm_job_id'], '12345')
        wrapped = shlex.split(command[command.index('--wrap') + 1])
        self.assertEqual(wrapped[0], 'exec')
        self.assertEqual(wrapped[1], str(self.root / '.venv-image/bin/python'))
        snapshot = json.loads(Path(wrapped[-1]).read_text())
        self.assertEqual(snapshot['prompt'], request['prompt'])
        self.assertNotIn(request['prompt'], command)

    def test_missing_image_environment_fails_before_sbatch(self):
        (self.root / '.venv-image/bin/python').unlink()
        with patch.object(media.subprocess, 'run') as run, self.assertRaises(FileNotFoundError):
            media.submit(self.parse(), media.prepare_request(self.parse()))
        run.assert_not_called()

    def test_image_runtime_loads_local_model_and_preserves_official_schedule(self):
        request = media.prepare_request(self.parse('image', '--prompt', '完整图片要求\n' + '细节' * 5000))
        pipe = Mock()
        pipe.config.sample_sigmas = [1, .9, .8, .7, .6, .5, .4, .3]
        image = Mock(size=(1024, 1024))
        image.save.side_effect = lambda f, **kw: f.write(b'PNG')
        pipe.return_value.images = [image]
        pipeline = Mock()
        pipeline.from_pretrained.return_value = pipe
        torch = Mock()
        torch.cuda.is_available.return_value = True
        torch.cuda.get_device_name.return_value = 'test gpu'
        torch.cuda.max_memory_allocated.return_value = 123
        with patch.dict(sys.modules, {'torch': torch, 'diffusers': types.SimpleNamespace(QwenImage21Pipeline=pipeline), 'PIL': types.SimpleNamespace(Image=Mock())}):
            result = media.run_image(request)
        self.assertTrue(pipeline.from_pretrained.call_args.kwargs['local_files_only'])
        pipe.enable_model_cpu_offload.assert_called_once()
        self.assertEqual(pipe.call_args.kwargs['prompt'], request['prompt'])
        self.assertNotIn('sigmas', pipe.call_args.kwargs)
        self.assertNotIn('num_inference_steps', pipe.call_args.kwargs)
        self.assertEqual(result['steps'], 8)
        self.assertEqual(Path(request['output_path']).read_bytes(), b'PNG')

    def test_slurm_rejection_is_not_reported_as_success(self):
        with patch.object(media.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['sbatch'])):
            with self.assertRaises(subprocess.CalledProcessError):
                media.submit(self.parse(), media.prepare_request(self.parse()))

    def test_waited_job_failure_returns_paths_and_real_error(self):
        args = self.parse('image', '--wait')
        request = media.prepare_request(args)
        def failed(command, **kwargs):
            result_file = Path(request['request_file']).with_suffix('.result.json')
            result_file.write_text(json.dumps({'status': 'failed', 'error': 'CUDA driver incompatible'}))
            raise subprocess.CalledProcessError(1, command, output='9391\n')
        with patch.object(media.subprocess, 'run', side_effect=failed):
            result = media.submit(args, request)
        self.assertEqual(result['slurm_job_id'], '9391')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'CUDA driver incompatible')
        self.assertTrue(Path(result['result_file']).is_file())

    def test_local_image_model_requires_turbo_sampling_schedule(self):
        (self.model / 'model_index.json').write_text(json.dumps({'_class_name': 'QwenImage21Pipeline'}))
        with self.assertRaises(ValueError):
            media.prepare_request(self.parse())

    def minimax_model(self):
        model = self.root / 'models/MiniMax-H3-Image-W4A8'
        model.mkdir(parents=True)
        for file in ('diffusion_models/minimax_h3_image_pruned_w4a8.safetensors', 'vae/minimax_h3_image_vae_fp16.safetensors'):
            path = model / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        encoder = self.root / 'models/Comfy-Org-MiniMax-H3/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'
        encoder.parent.mkdir(parents=True)
        encoder.touch()
        return model

    def test_minimax_uses_independent_environment_single_gpu_and_six_step_model(self):
        model = self.minimax_model()
        python = self.root / '.venv-h3-image/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        args = self.parse('image', '--image-model', 'minimax-h3-w4a8')
        request = media.prepare_request(args)
        self.assertEqual(request['image_model'], 'minimax-h3-w4a8')
        self.assertEqual(request['model_dir'], str(model))
        with patch.object(media.subprocess, 'run', return_value=Mock(stdout='12345\n')) as run:
            media.submit(args, request)
        command = run.call_args.args[0]
        self.assertIn('--gres=gpu:1', command)
        self.assertIn('--mem=90000M', command)
        self.assertIn('--job-name=h3_image_once', command)
        self.assertEqual(shlex.split(command[-1])[1], str(python))

    def test_minimax_accepts_sixteen_references_and_rejects_wrong_checkpoint(self):
        model = self.minimax_model()
        ref = self.root / 'ref.png'
        ref.touch()
        args = self.parse('image', '--image-model', 'minimax-h3-w4a8', '--reference-images', *([str(ref)] * 16))
        self.assertEqual(len(media.prepare_request(args)['reference_images']), 16)
        (model / 'diffusion_models/minimax_h3_image_pruned_w4a8.safetensors').unlink()
        with self.assertRaises(FileNotFoundError):
            media.prepare_request(args)

    def test_int8_reuses_existing_vae_and_encoder_and_requests_one_gpu(self):
        w4 = self.minimax_model()
        model = self.root / 'models/MiniMax-H3-Image-INT8'
        weight = model / 'diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors'
        weight.parent.mkdir(parents=True)
        weight.touch()
        python = self.root / '.venv-h3-image/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        args = self.parse('image', '--image-model', 'minimax-h3-int8')
        request = media.prepare_request(args)
        self.assertEqual(request['unet_name'], weight.name)
        self.assertEqual(request['model_dir'], str(model))
        self.assertEqual(request['vae_dir'], str(w4 / 'vae'))
        with patch.object(media.subprocess, 'run', return_value=Mock(stdout='9393\n')) as run:
            media.submit(args, request)
        self.assertIn('--gres=gpu:1', run.call_args.args[0])
        self.assertIn(str(python), run.call_args.args[0][-1])

    def test_comfy_process_cleanup_on_render_failure(self):
        request = media.prepare_request(self.parse('video'))
        service = Mock()
        service.validate.return_value = {'output_path': request['output_path']}
        service.jobs = {}
        def render(job):
            (service.INP / 'temporary-reference.png').write_bytes(b'converted-image')
            (service.OUT / 'partial.mp4').write_bytes(b'partial-video')
            raise RuntimeError('inference failed')
        service.render.side_effect = render
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        with patch.object(media, 'load_video_service', return_value=service), patch.object(media, 'wait_for_comfy'), patch.object(media.subprocess, 'Popen', return_value=proc) as popen, self.assertRaisesRegex(RuntimeError, 'inference failed'):
            media.run_video(request)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
        self.assertIn('--input-directory', popen.call_args.args[0])
        self.assertIn('--output-directory', popen.call_args.args[0])
        self.assertFalse(service.INP.exists())
        self.assertFalse(service.OUT.exists())

    def test_video_success_cleans_only_its_comfy_input_directory(self):
        request = media.prepare_request(self.parse('video'))
        request['request_file'] = str(self.root / 'runs/job/request.json')
        original = self.root / 'original.png'
        original.write_bytes(b'original')
        other = self.root / 'ComfyUI/input/other-job.png'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'other-job')
        service = Mock()
        service.validate.return_value = {'output_path': request['output_path']}
        service.jobs = {}
        def render(job):
            (service.INP / 'converted.png').write_bytes(b'converted')
            (service.OUT / 'comfy-original.mp4').write_bytes(b'video')
            Path(request['output_path']).parent.mkdir(parents=True, exist_ok=True)
            Path(request['output_path']).write_bytes(b'video')
            job['prompt_id'] = 'prompt-id'
            return {'output_path': request['output_path']}
        service.render.side_effect = render
        proc = Mock()
        with patch.object(media, 'load_video_service', return_value=service), patch.object(media, 'wait_for_comfy'), patch.object(media.subprocess, 'Popen', return_value=proc):
            media.run_video(request)
        self.assertFalse(service.INP.exists())
        self.assertFalse(service.OUT.exists())
        self.assertEqual(Path(request['output_path']).read_bytes(), b'video')
        self.assertEqual(original.read_bytes(), b'original')
        self.assertEqual(other.read_bytes(), b'other-job')

    def test_failed_runtime_is_recorded_and_propagated(self):
        request = media.prepare_request(self.parse())
        request['request_file'] = str(self.root / 'request.json')
        with patch.object(media, 'run_image', side_effect=RuntimeError('CUDA out of memory')):
            with self.assertRaisesRegex(RuntimeError, 'CUDA out of memory'):
                media.execute(request)
        result = json.loads((self.root / 'request.result.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertIn('CUDA out of memory', result['error'])


if __name__ == '__main__':
    unittest.main()
