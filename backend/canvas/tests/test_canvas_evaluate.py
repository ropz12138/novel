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
    """测试布局评估"""

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    @patch("app.services.agents.tools.canvas_evaluate._get_db")
    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    def test_evaluate_returns_score_and_suggestions(self, mock_model, mock_db, mock_work_id):
        """评估应返回评分和建议"""
        mock_work_id.return_value = "test-work-id"

        # Mock 数据库查询
        mock_node = MagicMock()
        mock_node.id = "1"
        mock_node.type = "idea"
        mock_node.title = "测试"
        mock_node.layer = 0
        mock_node.extra_data = {}

        mock_edge = MagicMock()
        mock_edge.source_id = "1"
        mock_edge.target_id = "2"
        mock_edge.edge_type = "contains"

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.side_effect = [[mock_node], [mock_edge]]
        mock_db.return_value = mock_session

        mock_model.return_value = json.dumps({
            "score": 85,
            "issues": ["节点分布略显不均"],
            "suggestions": ["建议调整大纲节点位置"],
        })

        result = json.loads(evaluate_layout())
        assert result["score"] == 85
        assert len(result["issues"]) > 0
        assert len(result["suggestions"]) > 0

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    def test_evaluate_no_work_id(self, mock_work_id):
        """没有 work_id 应返回错误"""
        mock_work_id.return_value = None
        result = json.loads(evaluate_layout())
        assert result.get("error") is not None

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    @patch("app.services.agents.tools.canvas_evaluate._get_db")
    def test_evaluate_empty_canvas(self, mock_db, mock_work_id):
        """空画布应返回提示"""
        mock_work_id.return_value = "test-work-id"

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_db.return_value = mock_session

        result = json.loads(evaluate_layout())
        assert result["score"] == 0
        assert "画布为空" in result["issues"][0]

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    @patch("app.services.agents.tools.canvas_evaluate._get_db")
    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    def test_evaluate_handles_model_error(self, mock_model, mock_db, mock_work_id):
        """模型调用失败应返回错误信息"""
        mock_work_id.return_value = "test-work-id"

        mock_node = MagicMock()
        mock_node.id = "1"
        mock_node.type = "idea"
        mock_node.title = "测试"
        mock_node.layer = 0
        mock_node.extra_data = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_node]
        mock_db.return_value = mock_session

        mock_model.side_effect = Exception("API 调用失败")

        result = json.loads(evaluate_layout())
        assert result.get("error") is not None

    @patch("app.services.agents.tools.canvas_evaluate._get_current_work_id")
    @patch("app.services.agents.tools.canvas_evaluate._get_db")
    @patch("app.services.agents.tools.canvas_evaluate._call_multimodal_model")
    def test_evaluate_handles_invalid_json_response(self, mock_model, mock_db, mock_work_id):
        """模型返回非 JSON 应有容错处理"""
        mock_work_id.return_value = "test-work-id"

        mock_node = MagicMock()
        mock_node.id = "1"
        mock_node.type = "idea"
        mock_node.title = "测试"
        mock_node.layer = 0
        mock_node.extra_data = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_node]
        mock_db.return_value = mock_session

        mock_model.return_value = "这不是一个 JSON 响应"

        result = json.loads(evaluate_layout())
        assert result.get("score") is not None or result.get("error") is not None
