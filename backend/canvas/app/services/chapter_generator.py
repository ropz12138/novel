import json
import logging
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def generate_chapter(context: dict) -> dict:
    model_config = settings.get_model_config()
    client = OpenAI(base_url=model_config["base_url"], api_key=model_config["api_key"])

    prompt = _build_prompt(context)

    response = client.chat.completions.create(
        model=settings.default_model,
        messages=[
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    result_text = response.choices[0].message.content

    return _parse_response(result_text)


def _get_system_prompt() -> str:
    return """你是一个专业的小说写作助手。你需要根据提供的上下文信息生成小说章节。

你的输出必须是严格的JSON格式，包含以下字段：
{
    "content": "章节正文内容",
    "summary": "章节摘要（100字以内）",
    "new_facts": ["本章新增的事实或设定"],
    "foreshadows": ["本章埋下的伏笔"]
}

注意：
1. 正文内容应该是完整的小说章节
2. 摘要要简洁概括本章主要内容
3. 新增事实是本章中首次出现的信息
4. 伏笔是为后续剧情埋下的线索
5. 如果有"禁止泄露"的信息，绝对不能在正文中明说，只能暗示
6. 每段关联内容都有明确的写作指令，请严格按照指令处理"""


def _build_prompt(context: dict) -> str:
    parts = []

    parts.append(f"## 章节标题\n{context['chapter_title']}")

    if context["chapter_content"]:
        parts.append(f"## 已有内容\n{context['chapter_content']}")

    # 按关系类型组装上下文
    if context.get("related_contexts"):
        parts.append("## 关联内容与写作指令")
        parts.append("")
        for ctx in context["related_contexts"]:
            parts.append(f"### 【{ctx['edge_type']}】{ctx['title']}")
            parts.append(f"节点类型：{ctx['type']}")
            parts.append(f"内容：")
            parts.append(ctx["content"])
            parts.append(f"")
            parts.append(f"→ {ctx['instruction']}")
            parts.append("")

    # 禁止泄露的信息
    if context.get("forbidden_reveals"):
        parts.append("## ⚠️ 禁止泄露的信息（绝对不能在正文中明说）")
        for node in context["forbidden_reveals"]:
            parts.append(f"- {node['title']}：{node['content'][:100]}...")
        parts.append("")

    # 额外指令
    if context.get("extra_instructions"):
        parts.append(f"## 额外指令\n{context['extra_instructions']}")

    parts.append("## 输出要求\n请根据以上信息生成小说章节，输出严格的JSON格式。")

    return "\n".join(parts)


def _parse_response(text: str) -> dict:
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text.strip())

        return {
            "content": result.get("content", ""),
            "summary": result.get("summary", ""),
            "new_facts": result.get("new_facts", []),
            "foreshadows": result.get("foreshadows", []),
        }
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return {
            "content": text,
            "summary": "",
            "new_facts": [],
            "foreshadows": [],
        }
