"""deepseek-v4-flash-0731 把思考和工具调用塞进 content 时的拆分。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


EMBEDDED_TOOL_MODEL = "deepseek-v4-flash-0731"
DSML_TOOL_CALLS_OPEN = "<｜DSML｜tool_calls>"
_THINK_CLOSE = "</think>"
_TOOL_BLOCK = re.compile(
    r"<｜DSML｜tool_calls>\s*(.*?)\s*</｜DSML｜tool_calls>",
    re.DOTALL,
)
_INVOKE = re.compile(
    r'<｜DSML｜invoke name="([^"]+)">\s*(.*?)\s*</｜DSML｜invoke>',
    re.DOTALL,
)
_PARAMETER = re.compile(
    r'<｜DSML｜parameter name="([^"]+)" string="(true|false)">\s*(.*?)\s*</｜DSML｜parameter>',
    re.DOTALL,
)


@dataclass(frozen=True)
class EmbeddedToolContent:
    reasoning: str
    content: str
    tool_calls: list[dict]


def _remainder_is_blank(text: str, matches: list[re.Match]) -> bool:
    rest = text
    for match in matches:
        rest = rest.replace(match.group(0), "", 1)
    return not rest.strip()


def _arguments_from_parameters(body: str) -> dict | None:
    parameters = list(_PARAMETER.finditer(body))
    if not parameters or not _remainder_is_blank(body, parameters):
        return None
    names = [match.group(1) for match in parameters]
    if names == ["arguments"]:
        if parameters[0].group(2) != "false":
            return None
        try:
            arguments = json.loads(parameters[0].group(3))
        except json.JSONDecodeError:
            return None
        if not isinstance(arguments, dict):
            return None
        return arguments
    if "arguments" in names:
        return None
    arguments: dict = {}
    for match in parameters:
        name, is_string, raw = match.group(1), match.group(2), match.group(3)
        if not name or name in arguments:
            return None
        if is_string == "true":
            arguments[name] = raw
            continue
        try:
            arguments[name] = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return arguments


def parse_embedded_tool_content(text: str) -> EmbeddedToolContent | None:
    """一个工具把参数包成 arguments JSON；多个工具按字段展开。拆不开时返回 None。"""
    if DSML_TOOL_CALLS_OPEN not in text:
        return None
    blocks = _TOOL_BLOCK.findall(text)
    if not blocks:
        return None
    tool_calls = []
    for block in blocks:
        invokes = list(_INVOKE.finditer(block))
        if not invokes or not _remainder_is_blank(block, invokes):
            return None
        for match in invokes:
            name = match.group(1).strip()
            arguments = _arguments_from_parameters(match.group(2))
            if not name or arguments is None:
                return None
            tool_calls.append({"name": name, "arguments": arguments})
    if not tool_calls:
        return None
    head = text.split(DSML_TOOL_CALLS_OPEN, 1)[0]
    if _THINK_CLOSE in head:
        reasoning, visible = head.rsplit(_THINK_CLOSE, 1)
    else:
        reasoning, visible = "", head
    return EmbeddedToolContent(
        reasoning=reasoning.strip(),
        content=visible.strip(),
        tool_calls=tool_calls,
    )
