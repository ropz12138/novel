"""Prompt and context helpers for node content edits performed by update_node."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from models.edge import Edge
from models.node import Node


EDIT_CHAPTER_SYSTEM = """你是节点文本编辑助手。任务：按用户指令对已有节点 content 做最小范围修改。

【铁律】
1. "用户编辑指令"是用户原话，逐字遵守，禁止擅自扩写无关内容。
2. 只修改与指令直接相关的段落，其余段落不得改动。
3. 输出必须是合法 JSON，且仅包含 JSON，格式见说明；禁止输出 JSON 以外的任何文字。
4. old_text 必须从原文精确复制，用于后端校验。
5. 保持原节点文本的文体、格式和信息层级；章节正文则保持原叙事风格。
6. 禁止生成提纲、规划性文字。
7. `[[PLOT]]...[[/PLOT]]` 是纯标记：只能包裹当前正文中已经存在的连续原文，不能为了满足人物、行动、结果而改写、压缩或新增总结句；给正文加标签时，除标签外不得改变正文字符。`**...**` 仅是普通 Markdown 粗体。

【输出格式】
{
  "edits": [
    {
      "type": "replace",
      "paragraph_index": 3,
      "old_text": "从原文精确复制的待改片段或整段",
      "new_text": "修改后的文本"
    },
    {
      "type": "insert_after",
      "paragraph_index": 2,
      "new_text": "插入的新段落全文"
    },
    {
      "type": "delete",
      "paragraph_index": 5,
      "old_text": "待删除段落的完整原文"
    }
  ]
}

type 取值：replace（替换）、insert_after（在 paragraph_index 段后插入；0 表示文首前插入）、delete（删除整段，old_text 必须与该段全文一致）。
paragraph_index 为 1-based，与正文中 [N] 段落编号一致。"""


def _format_numbered_paragraphs(content: str) -> str:
    from services.chapter_edit_service import split_paragraphs

    paragraphs = split_paragraphs(content)
    if not paragraphs:
        return "（空）"
    return "\n\n".join(f"[{i + 1}] {paragraph}" for i, paragraph in enumerate(paragraphs))


def build_edit_chapter_messages(
    edit_instruction,
    content,
    context,
    global_context="",
    prev_chapter="",
    elements=None,
):
    system = EDIT_CHAPTER_SYSTEM
    if global_context:
        system = global_context + "\n\n" + system

    sections = [
        "======= 用户编辑指令（最高优先级，逐字遵守，禁止改写扩写）=======\n"
        f"{edit_instruction}\n"
        "=====================================================================",
        "======= 当前节点 content（按段落编号）=======\n"
        f"{_format_numbered_paragraphs(content)}\n"
        "=========================================",
    ]
    if prev_chapter:
        sections.append(
            "======= 上一章正文（承接参考）=======\n"
            f"{prev_chapter}\n"
            "====================================="
        )
    if elements:
        element_text = "\n".join(f"- {item['title']}：{item['content']}" for item in elements)
        sections.append(
            "======= 本章情节元素（修改时勿破坏已涵盖的情节）=======\n"
            f"{element_text}\n"
            "======================================================"
        )
    if context:
        sections.append(
            "======= 写作上下文（agent 已备齐，直接使用）=======\n"
            f"{context}\n"
            "================================================="
        )

    return [
        SystemMessage(content=system),
        HumanMessage(content="\n\n".join(sections)),
    ]


def parse_edits_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict) or "edits" not in data:
        raise ValueError("LLM 输出缺少 edits 字段")
    if not isinstance(data["edits"], list):
        raise ValueError("edits 必须是数组")
    return data


def read_previous_chapter_content(db, previous_chapter_node_id) -> str:
    if not previous_chapter_node_id:
        return ""
    node = db.query(Node).filter(Node.id == previous_chapter_node_id).first()
    return node.content or "" if node else ""


def collect_chapter_elements(db, chapter_node_id, work_id) -> list:
    elements = (
        db.query(Node)
        .join(Edge, Edge.source_id == Node.id)
        .filter(
            Edge.target_id == chapter_node_id,
            Edge.edge_type.in_(("contains", "包含")),
            Edge.work_id == work_id,
            Node.type == "element",
        )
        .all()
    )
    return [{"title": element.title, "content": element.content or ""} for element in elements]
