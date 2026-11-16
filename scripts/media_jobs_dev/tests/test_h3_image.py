import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('h3_image', Path(__file__).resolve().parents[1] / 'h3_image.py')
h3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h3)


class H3ImageTests(unittest.TestCase):
    def request(self, root):
        return dict(project=str(root), model_dir=str(root / 'models/MiniMax-H3-Image-W4A8'),
                    image_model='minimax-h3-w4a8', unet_name='minimax_h3_image_pruned_w4a8.safetensors',
                    vae_dir=str(root / 'models/MiniMax-H3-Image-W4A8/vae'),
                    prompt='完整中文立绘要求\n' * 5000 + '$(echo x) `false`',
                    reference_images=[], width=768, height=1024, seed=3,
                    output_path=str(root / 'portrait.png'))

    def test_workflow_preserves_full_prompt_six_steps_and_exact_output_size(self):
        request = self.request(Path('/local'))
        graph = h3.build_workflow(request)
        self.assertEqual(graph['4']['inputs']['prompt'], request['prompt'])
        self.assertEqual(graph['5']['inputs']['steps'], 6)
        self.assertEqual(graph['5']['inputs']['cfg'], 1)
        self.assertEqual(graph['5']['inputs']['sampler_name'], 'euler')
        self.assertEqual(graph['5']['inputs']['scheduler'], 'simple')
        self.assertGreaterEqual(graph['4']['inputs']['width'] * graph['4']['inputs']['height'], 2048 ** 2)
        self.assertEqual((graph['8']['inputs']['width'], graph['8']['inputs']['height']), (768, 1024))
        self.assertEqual(graph['1']['inputs']['unet_name'], 'minimax_h3_image_pruned_w4a8.safetensors')
        self.assertEqual(graph['10']['class_type'], 'ModelAttentionBackend')
        self.assertEqual(graph['10']['inputs'], {'model': ['1', 0], 'attention': 'pytorch attention'})
        self.assertEqual(graph['5']['inputs']['model'], ['10', 0])

    def test_references_keep_their_order(self):
        request = self.request(Path('/local'))
        request['reference_images'] = ['/original/first.jpg', '/original/second.png']
        graph = h3.build_workflow(request)
        self.assertEqual(graph['4']['inputs']['images.image_1'], ['ref_1', 0])
        self.assertEqual(graph['4']['inputs']['images.image_2'], ['ref_2', 0])
        self.assertEqual(graph['ref_1']['inputs']['image'], 'reference_1.jpg')
        self.assertEqual(graph['ref_2']['inputs']['image'], 'reference_2.png')

    def test_int8_only_changes_the_image_weight_for_a_fair_comparison(self):
        request = self.request(Path('/local'))
        w4_graph = h3.build_workflow(request)
        request.update(image_model='minimax-h3-int8', unet_name='minimax_h3_image_pruned_int8_convrot.safetensors')
        graph = h3.build_workflow(request)
        self.assertEqual(graph['1']['inputs']['unet_name'], request['unet_name'])
        self.assertEqual({k: v for k, v in graph.items() if k != '1'}, {k: v for k, v in w4_graph.items() if k != '1'})

    def test_server_failure_cleans_up_and_preserves_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.request(root)
            request['request_file'] = str(root / 'runs/request.json')
            source = root / 'source.png'
            source.write_bytes(b'original')
            request['reference_images'] = [str(source)]
            process = Mock()
            with patch.object(h3.subprocess, 'Popen', return_value=process) as popen, patch.object(h3, 'wait_for_comfy', side_effect=RuntimeError('server failed')):
                with self.assertRaisesRegex(RuntimeError, 'server failed'):
                    h3.run_image(request)
            command = popen.call_args.args[0]
            self.assertIn('ComfyUI-h3-image-dev/main.py', command[2])
            self.assertIn('--enable-triton-backend', command)
            self.assertIn('--offline', command)
            self.assertIn('--disable-all-custom-nodes', command)
            self.assertNotIn('--lowvram', command)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertEqual(source.read_bytes(), b'original')
            inputs = Path(command[command.index('--input-directory') + 1])
            self.assertFalse(inputs.exists())
            config = root / 'runs/h3-model-paths.yaml'
            self.assertIn(request['model_dir'], config.read_text())

    def test_execution_error_is_reported_instead_of_polling_forever(self):
        opener = Mock()
        history = {'p1': {'status': {'completed': False, 'status_str': 'error', 'messages': [['execution_error', {'exception_message': 'CUDA out of memory'}]]}}}
        response = Mock()
        response.read.return_value = json.dumps(history).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener.open.return_value = response
        process = Mock()
        process.poll.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'CUDA out of memory'):
            h3.wait_for_image(opener, 'http://localhost', 'p1', process)


if __name__ == '__main__':
    unittest.main()
