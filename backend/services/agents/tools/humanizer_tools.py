"""小说自然化规则读取工具：编辑和保存由 supervisor 执行。"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "fiction_humanizer.txt"


class HumanizeNodeContentInput(BaseModel):
    node_id: str = Field(description="agent 接下来准备自然化编辑的章节节点 ID")
    reason: str | None = Field(default=None, description="读取规则的原因")


async def _humanize_node_content_async(node_id: str, reason: str | None = None) -> str:
    try:
        skill_content = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return json.dumps({
            "success": False,
            "error": f"读取小说自然化规则失败: {exc}",
        }, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "status": "skill_loaded",
        "changed": False,
        "node_id": node_id,
        "reason": reason,
        "skill_content": skill_content,
        "message": (
            "小说自然化规则已加载，章节编辑待 agent 执行。"
            "请读取目标章节最新正文及相关设定，按规则自行改写，"
            "通过 update_node 的 content 保存完整修改稿，再读取正文核对结果。"
        ),
    }, ensure_ascii=False)


humanize_node_content = StructuredTool.from_function(
    coroutine=_humanize_node_content_async,
    name="humanize_node_content",
    description=(
        "读取并完整返回小说去 AI 味编辑规则（skill_content），供 agent 本体执行章节自然化。"
        "此工具仅加载规则；skill_loaded 表示规则读取成功，章节编辑尚待执行。"
        "读取规则后，agent 用 read_node_content 获取最新正文和相关设定，"
        "自行完成改写，再用 update_node.content 保存完整章节，最后重新读取核对。"
        "适用于用户明确要求去 AI 味、自然化、减少机器感或改得更像真人的章节。"
    ),
    args_schema=HumanizeNodeContentInput,
)

humanizer_tools = [humanize_node_content]
