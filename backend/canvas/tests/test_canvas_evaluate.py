"""多模态画布评估工具测试 — TDD：验证画布渲染和模型调用。"""
import json
import base64
from unittest.mock import patch, MagicMock

from app.services.agents.tools.canvas_evaluate import (
    render_canvas_to_image,
    evaluate_layout,
)


class TestRenderCanvasToImage:
    """测试画布渲染为图片"""

    def test_render_empty_canvas(self):
        """空画布应返回有效 PNG 图片"""
        img_base64 = render_canvas_to_image([], [])
        assert img_base64 is not None
        assert len(img_base64) > 0
        # 验证是有效的 base64
        img_bytes = base64.b64decode(img_base64)
        # PNG 文件头
        assert img_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_single_node(self):
        """单节点应正常渲染"""
        nodes = [{"id": "1", "type": "idea", "title": "测试灵感", "layer": 0}]
        img_base64 = render_canvas_to_image(nodes, [])
        assert img_base64 is not None
        assert len(img_base64) > 0

    def test_render_multiple_nodes_with_edges(self):
        """多节点+连线应正常渲染"""
        nodes = [
            {"id": "1", "type": "outline", "title": "大纲", "layer": 0},
            {"id": "2", "type": "chapter", "title": "第1章", "layer": 1},
            {"id": "3", "type": "character", "title": "主角", "layer": 2},
        ]
        edges = [
            {"source_id": "1", "target_id": "2", "edge_type": "contains"},
            {"source_id": "2", "target_id": "3", "edge_type": "character_appears"},
        ]
        img_base64 = render_canvas_to_image(nodes, edges)
        assert img_base64 is not None
        assert len(img_base64) > 0

    def test_render_nodes_with_custom_type(self):
        """自定义类型节点应正常渲染"""
        nodes = [
            {"id": "1", "type": "龙套逆袭", "title": "自定义类型", "layer": 0},
        ]
        img_base64 = render_canvas_to_image(nodes, [])
        assert img_base64 is not None


class TestEvaluateLayout:
    """测试布局评估 — 读前端上传的截图缓存文件，调多模态模型。"""

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_no_work_id(self, mock_work_id):
        """没有 work_id 应返回错误"""
        mock_work_id.return_value = None
        result = json.loads(evaluate_layout())
        assert result.get("error") is not None

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_no_screenshot_returns_error(self, mock_work_id, tmp_path, monkeypatch):
        """截图未就绪（文件不存在）应返回错误"""
        import app.services.agents.tools.canvas_evaluate as ce
        mock_work_id.return_value = "wk-noimg"
        monkeypatch.setattr(ce, "RENDER_DIR", tmp_path)
        result = json.loads(evaluate_layout())
        assert result.get("error") is not None
        assert "截图" in result["error"] or "未就绪" in result["error"]

    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_reads_screenshot_and_calls_model(self, mock_work_id, mock_model, tmp_path, monkeypatch):
        """有截图时应读取文件、调模型并返回评分"""
        import app.services.agents.tools.canvas_evaluate as ce
        mock_work_id.return_value = "wk-1"
        monkeypatch.setattr(ce, "RENDER_DIR", tmp_path)
        (tmp_path / "wk-1.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'fake-image')

        mock_model.return_value = json.dumps({
            "score": 88,
            "issues": ["节点分布不均"],
            "suggestions": ["调整大纲位置"],
        })

        result = json.loads(evaluate_layout())
        assert result["score"] == 88
        # 模型收到截图 base64（解码后以 PNG 头开头）
        called_image = mock_model.call_args.args[0]
        assert base64.b64decode(called_image)[:8] == b'\x89PNG\r\n\x1a\n'

    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_handles_model_error(self, mock_work_id, mock_model, tmp_path, monkeypatch):
        """模型调用失败应返回错误"""
        import app.services.agents.tools.canvas_evaluate as ce
        mock_work_id.return_value = "wk-1"
        monkeypatch.setattr(ce, "RENDER_DIR", tmp_path)
        (tmp_path / "wk-1.png").write_bytes(b'\x89PNG\r\n\x1a\nfake')
        mock_model.side_effect = Exception("API 调用失败")

        result = json.loads(evaluate_layout())
        assert result.get("error") is not None

    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_handles_invalid_json_response(self, mock_work_id, mock_model, tmp_path, monkeypatch):
        """模型返回非 JSON 应有容错"""
        import app.services.agents.tools.canvas_evaluate as ce
        mock_work_id.return_value = "wk-1"
        monkeypatch.setattr(ce, "RENDER_DIR", tmp_path)
        (tmp_path / "wk-1.png").write_bytes(b'\x89PNG\r\n\x1a\nfake')

        mock_model.return_value = "这不是一个 JSON 响应"

        result = json.loads(evaluate_layout())
        assert result.get("score") is not None or result.get("error") is not None
