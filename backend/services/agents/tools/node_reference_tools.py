"""只读原文引用：校验当前作品中的原文并生成可持久保留在消息中的链接。"""
import asyncio
import json
from urllib.parse import urlencode

from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from models.node import Node
from services.agent_paragraphs import MARKDOWN, segmentation_mode, split_paragraphs


class NodeReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="当前作品中的节点 UUID")
    part: Literal["content", "notes"] = Field(description="content 引用该节点正文，notes 引用章节笔记。段落号来自 read_node_content 返回的 content_paragraphs 或 notes_paragraphs 中的 number。Markdown 标题和列表条目可以各自编号。")
    start_paragraph: int = Field(ge=1, description="起始段落号，包含该段。")
    end_paragraph: int = Field(ge=1, description="结束段落号，包含该段。单段引用时与 start_paragraph 相同。")


class CreateNodeReferencesInput(BaseModel):
    references: list[NodeReferenceInput] = Field(min_length=1, max_length=10, description="批量生成原文定位引用，一次最多 10 条")


def make_reference(node_id, title, content, start_paragraph, end_paragraph, part, node_type="chapter"):
    if start_paragraph > end_paragraph:
        return {"success": False, "error": "invalid_range", "message": "起点大于终点"}
    mode = segmentation_mode(node_type, field=part)
    paragraphs = split_paragraphs(content or "", mode)
    selected = [paragraph for paragraph in paragraphs if start_paragraph <= paragraph.number <= end_paragraph]
    if not selected or selected[0].number != start_paragraph or selected[-1].number != end_paragraph:
        label = "笔记" if part == "notes" else "正文"
        return {"success": False, "error": "paragraph_out_of_range", "message": f"段落号超出当前{label}"}
    query = {
        "node_id": node_id,
        "part": part,
        "start_paragraph": start_paragraph,
        "end_paragraph": end_paragraph,
    }
    if mode == MARKDOWN:
        query["segmentation"] = "markdown-v1"
        query["start"] = selected[0].start
        query["end"] = selected[-1].end
    href = "/node-reference?" + urlencode(query)
    return {
        "success": True, "node_id": node_id, "title": title, "part": part,
        "start_paragraph": start_paragraph, "end_paragraph": end_paragraph,
        "url": href, "markdown": f"[查看原文]({href})",
    }


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
                continue
            if item["part"] == "notes" and node.type != "chapter":
                results.append({"success": False, "error": "notes_unavailable", "node_id": node.id, "message": "只有章节节点有笔记"})
                continue
            text = node.content or ""
            if item["part"] == "notes":
                from models.chapter import Chapter
                chapter = db.query(Chapter).filter(Chapter.node_id == node.id, Chapter.work_id == work_id).first()
                text = chapter.notes if chapter and chapter.notes else ""
            results.append(make_reference(
                node.id, node.title, text, item["start_paragraph"], item["end_paragraph"], item["part"], node.type,
            ))
        return json.dumps({"references": results}, ensure_ascii=False)
    finally:
        db.close()


async def _create_node_references_async(references):
    return await asyncio.to_thread(_create_node_references, references)


create_node_references = StructuredTool.from_function(
    func=_create_node_references,
    coroutine=_create_node_references_async,
    name="create_node_references",
    description=("只读批量创建节点原文定位引用。先用 read_node_content 读取编号文本，再传入节点 UUID、part 和段落号。"
                 "段落号使用返回的 number。part 为 content 时使用 content_paragraphs，part 为 notes 时使用该章节的 notes_paragraphs。"
                 "非章节正文和章节笔记按 Markdown 标题、列表条目等结构编号。"
                 "工具按所选部分校验段落范围并返回 markdown 链接；把返回的 markdown 原样放在对应结论之后，"
                 "用户可在 Web 点击打开该段。段落号超出所选部分时，重新读取后再创建。"),
    args_schema=CreateNodeReferencesInput,
)
