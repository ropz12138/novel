"""只读原文引用：校验当前作品中的原文并生成可持久保留在消息中的链接。"""
import asyncio
import json
from urllib.parse import urlencode

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.node import Node


class NodeReferenceInput(BaseModel):
    node_id: str = Field(description="当前作品中的节点 UUID")
    quote: str = Field(min_length=1, description="节点正文中一段连续、可唯一匹配的原文，保留原始 Markdown 文本")


class CreateNodeReferencesInput(BaseModel):
    references: list[NodeReferenceInput] = Field(min_length=1, description="批量生成原文定位引用")


def make_reference(node_id, title, content, quote):
    start = content.find(quote)
    if not quote or start < 0:
        return {"success": False, "error": "quote_not_found", "message": "请读取最新正文，使用其中的连续原文。"}
    if content.find(quote, start + 1) >= 0:
        return {"success": False, "error": "ambiguous_quote", "message": "原文出现多次，请扩展引用范围使其唯一。"}
    href = "/node-reference?" + urlencode({"node_id": node_id, "quote": quote})
    return {"success": True, "node_id": node_id, "title": title, "quote": quote,
            "url": href, "markdown": f"[查看原文]({href})"}


def _create_node_references(references):
    from database import SessionLocal
    from services.agents.supervisor import get_context
    work_id = get_context().get("work_id")
    if not work_id:
        return json.dumps({"success": False, "error": "missing_work"})
    db = SessionLocal()
    try:
        results = []
        for item in references:
            item = item if isinstance(item, dict) else item.model_dump()
            node = db.query(Node).filter(Node.id == item["node_id"], Node.work_id == work_id).first()
            if node is None:
                results.append({"success": False, "error": "node_not_found", "node_id": item["node_id"]})
            else:
                results.append(make_reference(node.id, node.title, node.content or "", item["quote"]))
        return json.dumps({"references": results}, ensure_ascii=False)
    finally:
        db.close()


async def _create_node_references_async(references):
    return await asyncio.to_thread(_create_node_references, references)


create_node_references = StructuredTool.from_function(
    func=_create_node_references,
    coroutine=_create_node_references_async,
    name="create_node_references",
    description=("只读批量创建节点原文定位引用。先读取节点正文，再传入节点 UUID 和连续原文。"
                 "工具校验原文唯一性并返回 markdown 链接；在回答的对应分析意见后直接使用返回的 markdown，"
                 "用户可在 Web 点击查看段落。引用失败时按返回提示调整原文后再创建。"),
    args_schema=CreateNodeReferencesInput,
)
