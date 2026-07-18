"""多模态画布评估工具 — 读取前端上传的画布截图，调用多模态模型评估布局质量。

截图由前端 ReactFlow 用 html-to-image 渲染后上传（POST /works/{id}/canvas/render），
保证"和前端显示一模一样"。本工具只负责取截图缓存 + 调多模态模型。
"""
import json
import base64
import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.node import Node
from app.models.edge import Edge

logger = logging.getLogger(__name__)

# 前端上传的画布截图缓存目录（多 worker 共享，落盘）
# canvas_evaluate.py 位于 backend/canvas/app/services/agents/tools/，parents[6] = 项目根
RENDER_DIR = Path(__file__).resolve().parents[6] / ".run" / "canvas_renders"


def get_render_path(work_id: str) -> Path:
    """返回某作品画布截图的缓存路径。"""
    return RENDER_DIR / f"{work_id}.png"

# 节点类型颜色映射（与 node_types.STANDARD_NODE_TYPES 一致，仅 7 类）
DEFAULT_COLORS = {
    "outline": "#3B82F6",       # 蓝色
    "volume": "#6366F1",        # 靛蓝
    "plot": "#F97316",          # 橙色
    "chapter": "#10B981",       # 绿色
    "character": "#EC4899",     # 粉色
    "worldbuilding": "#8B5CF6", # 紫色
    "style": "#A855F7",         # 紫罗兰
}
DEFAULT_NODE_COLOR = "#94A3B8"  # 默认灰色

# 布局常量
NODE_WIDTH = 180
NODE_HEIGHT = 60
LAYER_GAP_Y = 120
NODE_GAP_X = 40
PADDING = 50


def _get_db():
    """获取数据库会话"""
    from app.database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


def _get_color_for_type(node_type: str, extra_data: dict = None) -> str:
    """获取节点颜色：优先使用 extra_data 中的颜色，否则使用默认映射。"""
    if extra_data and extra_data.get("color"):
        return extra_data["color"]
    return DEFAULT_COLORS.get(node_type, DEFAULT_NODE_COLOR)


def render_canvas_to_image(nodes: list[dict], edges: list[dict]) -> str:
    """将画布渲染为 PNG 图片，返回 base64 编码。

    Args:
        nodes: 节点列表，每项包含 id, type, title, layer, extra_data(可选)
        edges: 边列表，每项包含 source_id, target_id, edge_type

    Returns:
        base64 编码的 PNG 图片字符串
    """
    if not nodes:
        # 空画布
        img = Image.new("RGB", (400, 300), "white")
        draw = ImageDraw.Draw(img)
        draw.text((150, 140), "空画布", fill="gray")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    # 按 layer 分组
    layers = {}
    for node in nodes:
        layer = node.get("layer", 0)
        if layer not in layers:
            layers[layer] = []
        layers[layer].append(node)

    sorted_layers = sorted(layers.keys())

    # 计算画布尺寸
    max_nodes_in_layer = max(len(layers[l]) for l in sorted_layers)
    canvas_width = max_nodes_in_layer * (NODE_WIDTH + NODE_GAP_X) + PADDING * 2
    canvas_height = len(sorted_layers) * (NODE_HEIGHT + LAYER_GAP_Y) + PADDING * 2

    # 创建画布
    img = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(img)

    # 尝试加载字体
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font = ImageFont.load_default()
        title_font = font

    # 计算节点位置并绘制
    node_positions = {}
    for layer_idx, layer in enumerate(sorted_layers):
        nodes_in_layer = layers[layer]
        y = PADDING + layer_idx * (NODE_HEIGHT + LAYER_GAP_Y)
        total_width = len(nodes_in_layer) * NODE_WIDTH + (len(nodes_in_layer) - 1) * NODE_GAP_X
        start_x = (canvas_width - total_width) // 2

        for node_idx, node in enumerate(nodes_in_layer):
            x = start_x + node_idx * (NODE_WIDTH + NODE_GAP_X)
            node_positions[node["id"]] = (x, y)

            # 绘制节点矩形
            color = _get_color_for_type(node.get("type", ""), node.get("extra_data"))
            draw.rounded_rectangle(
                [x, y, x + NODE_WIDTH, y + NODE_HEIGHT],
                radius=10,
                fill=color,
                outline="white",
                width=2
            )

            # 绘制类型标签
            type_label = node.get("type", "")[:8]
            draw.text((x + 10, y + 5), type_label, fill="white", font=title_font)

            # 绘制标题
            title = node.get("title", "")[:15]
            draw.text((x + 10, y + 25), title, fill="white", font=font)

    # 绘制边
    for edge in edges:
        source_pos = node_positions.get(edge.get("source_id"))
        target_pos = node_positions.get(edge.get("target_id"))
        if source_pos and target_pos:
            # 计算连线起点和终点
            sx = source_pos[0] + NODE_WIDTH // 2
            sy = source_pos[1] + NODE_HEIGHT
            tx = target_pos[0] + NODE_WIDTH // 2
            ty = target_pos[1]

            # 绘制箭头线
            draw.line([(sx, sy), (tx, ty)], fill="#64748B", width=2)
            # 箭头头部
            draw.polygon([(tx, ty), (tx - 6, ty - 10), (tx + 6, ty - 10)], fill="#64748B")

    # 转为 base64
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _get_multimodal_config():
    """获取多模态模型配置"""
    from app.config import settings
    return settings.get_model_config("mimo-v2.5")


def _call_multimodal_model(image_base64: str, prompt: str) -> str:
    """调用多模态模型进行图片分析。

    Args:
        image_base64: base64 编码的图片
        prompt: 提示词

    Returns:
        模型返回的文本
    """
    import openai

    config = _get_multimodal_config()
    client = openai.OpenAI(
        base_url=config["base_url"],
        api_key=config["api_key"],
    )

    response = client.chat.completions.create(
        model="mimo-v2.5",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ],
            }
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content


def evaluate_layout(reason: str = None) -> str:
    """评估当前画布布局质量，返回 JSON 格式的评估报告。

    Args:
        reason: 调用原因（仅用于日志）

    Returns:
        JSON 字符串，包含 score, issues, suggestions
    """
    try:
        # 获取当前 work_id
        work_id = _get_current_work_id()
        if not work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

        # 读取前端上传的画布截图（html-to-image 渲染，与前端显示一致）
        screenshot_path = get_render_path(work_id)
        if not screenshot_path.exists():
            return json.dumps(
                {"error": "画布截图未就绪（前端尚未上传），请稍后或先操作画布触发截图"},
                ensure_ascii=False,
            )
        image_base64 = base64.b64encode(screenshot_path.read_bytes()).decode()

        # 构建提示词
        prompt = """请评估这张小说创作知识图谱的布局质量。评估维度：

1. **节点分布**：节点是否均匀分布，有无重叠或过于拥挤？
2. **连线分布**：连线走向是否清晰合理，有无相互交叉、重叠或杂乱缠绕？
3. **层级清晰度**：从上到下的层级关系是否清晰（主题→大纲→章节）？
4. **要素关联**：角色、伏笔、冲突等要素是否合理关联？
5. **视觉美观**：整体布局是否美观，颜色区分是否清晰？

请严格按照以下 JSON 格式返回评估结果，不要包含其他文本：
{
  "score": 0-100的整数评分,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"]
}"""

        # 调用多模态模型
        response_text = _call_multimodal_model(image_base64, prompt)

        # 尝试解析 JSON
        try:
            # 提取 JSON 部分（模型可能返回额外文本）
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response_text[json_start:json_end])
                # 验证必要字段
                if "score" not in result:
                    result["score"] = 0
                if "issues" not in result:
                    result["issues"] = []
                if "suggestions" not in result:
                    result["suggestions"] = []
                return json.dumps(result, ensure_ascii=False)
            else:
                return json.dumps({
                    "score": 0,
                    "issues": ["模型返回格式异常"],
                    "suggestions": ["请重试"],
                    "raw_response": response_text[:200]
                }, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({
                "score": 0,
                "issues": ["模型返回非 JSON 格式"],
                "suggestions": ["请重试"],
                "raw_response": response_text[:200]
            }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"画布评估失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# LangChain Tool 定义
class EvaluateLayoutInput(BaseModel):
    """评估布局输入"""
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


evaluate_layout_tool = StructuredTool(
    name="evaluate_canvas_layout",
    description="评估当前画布的布局质量。使用多模态模型分析画布截图，返回评分、问题和改进建议。",
    func=evaluate_layout,
    args_schema=EvaluateLayoutInput,
    return_direct=False,
)
