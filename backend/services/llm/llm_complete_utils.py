import json
from typing import Any


class LLMCompleteError(Exception):
    """LLM 补全过程发生的异常。"""
    pass


def extract_openai_text(body: dict[str, Any]) -> str:
    """提取 OpenAI 响应体中的文本内容。"""
    try:
        choices = body.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content") or ""
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            return "".join(parts)
        return content
    except Exception as exc:
        raise LLMCompleteError(f"解析 OpenAI 响应文本失败: {exc}") from exc


def extract_anthropic_text(body: dict[str, Any]) -> str:
    """提取 Anthropic 响应体中的文本内容。"""
    try:
        content_blocks = body.get("content", [])
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "".join(text_parts)
    except Exception as exc:
        raise LLMCompleteError(f"解析 Anthropic 响应文本失败: {exc}") from exc
