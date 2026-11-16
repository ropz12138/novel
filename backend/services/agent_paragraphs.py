"""Agent 正文的段落映射。编号只用于阅读和定位，不写回原文。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from markdown_it import MarkdownIt

from node_types import STANDARD_NODE_TYPES

BLANK = "blank"
MARKDOWN = "markdown"
_LEAF_BLOCK_TYPES = frozenset({
    "heading_open", "paragraph_open", "table_open",
    "fence", "code_block", "html_block", "hr",
})
_MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")


@dataclass(frozen=True)
class Paragraph:
    number: int
    start: int
    end: int


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _lines(content: str):
    index = 0
    length = len(content)
    while index < length:
        start = index
        while index < length and content[index] != "\n":
            index += 1
        text_end = index
        if text_end > start and content[text_end - 1] == "\r":
            text_end -= 1
        if index < length:
            index += 1
        yield start, text_end


def segmentation_mode(node_type: str | None, *, field: str = "content") -> str:
    if field == "notes" or node_type == "chapter_note":
        return MARKDOWN
    if node_type == "chapter":
        return BLANK
    if node_type in STANDARD_NODE_TYPES:
        return MARKDOWN
    raise ValueError("缺少可确定分段模式的节点类型")


def _split_blank_paragraphs(content: str) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    start = None
    end = None
    for text_start, text_end in _lines(content or ""):
        if content[text_start:text_end].strip(" \t") == "":
            if start is not None:
                paragraphs.append(Paragraph(len(paragraphs) + 1, start, end))
                start = None
            continue
        if start is None:
            start = text_start
        end = text_end
    if start is not None:
        paragraphs.append(Paragraph(len(paragraphs) + 1, start, end))
    return paragraphs


def _split_markdown_paragraphs(content: str) -> list[Paragraph]:
    source = content or ""
    line_spans = list(_lines(source))
    if not source or not line_spans:
        return []
    paragraphs: list[Paragraph] = []
    last_end = -1
    for token in _MARKDOWN.parse(source):
        if token.type not in _LEAF_BLOCK_TYPES or not token.map:
            continue
        start_line, end_line = token.map
        if start_line < 0 or end_line <= start_line or start_line >= len(line_spans):
            continue
        end_line = min(end_line, len(line_spans))
        start = line_spans[start_line][0]
        end = line_spans[end_line - 1][1]
        if end <= start:
            continue
        if start < last_end:
            raise ValueError("Markdown 分段区间重叠")
        paragraphs.append(Paragraph(len(paragraphs) + 1, start, end))
        last_end = end
    return paragraphs


def split_paragraphs(content: str, mode: str = BLANK) -> list[Paragraph]:
    if mode == BLANK:
        return _split_blank_paragraphs(content)
    if mode == MARKDOWN:
        return _split_markdown_paragraphs(content)
    raise ValueError(f"未知分段模式: {mode}")


def content_reading_view(text: str, mode: str = BLANK) -> dict:
    source = text or ""
    return {
        "content_sha256": content_sha256(source),
        "content_paragraphs": [
            {"number": paragraph.number, "text": source[paragraph.start:paragraph.end]}
            for paragraph in split_paragraphs(source, mode)
        ],
    }


def format_numbered_text(text: str, mode: str = MARKDOWN) -> str:
    view = content_reading_view(text, mode)
    lines = [f"content_sha256：{view['content_sha256']}"]
    lines.extend(f"[{paragraph['number']}] {paragraph['text']}" for paragraph in view["content_paragraphs"])
    return "\n".join(lines)


def notes_reading_view(text: str) -> dict:
    view = content_reading_view(text, MARKDOWN)
    return {"notes_sha256": view["content_sha256"], "notes_paragraphs": view["content_paragraphs"]}


def present_content_record(record: dict) -> dict:
    shown = {key: value for key, value in record.items() if key != "content"}
    shown.update(content_reading_view(record.get("content") or "", segmentation_mode(record.get("type"))))
    return shown


def paragraph_index_for_span(content: str, start: int, old_text: str, mode: str = BLANK) -> int:
    """差异编号对应该段原文基线。空原文表示在此位置之前插入。"""
    paragraphs = split_paragraphs(content or "", mode)
    if not old_text:
        number = 0
        for paragraph in paragraphs:
            if paragraph.end <= start:
                number = paragraph.number
        return number
    end = start + len(old_text)
    for paragraph in paragraphs:
        if start < paragraph.end and end > paragraph.start:
            return paragraph.number
    return 1 if paragraphs else 0


def paragraph_bounds(content: str, start: int, end: int, mode: str = BLANK) -> tuple[int, int] | None:
    numbers = [
        paragraph.number
        for paragraph in split_paragraphs(content, mode)
        if start < paragraph.end and end > paragraph.start
    ]
    if not numbers:
        return None
    return numbers[0], numbers[-1]


def _field(item, name):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _raw_span(paragraphs: list[Paragraph], start_paragraph: int, end_paragraph: int, new: str) -> tuple[int, int]:
    start = paragraphs[start_paragraph - 1].start
    end = paragraphs[end_paragraph - 1].end
    if new == "":
        if start_paragraph == 1:
            if end_paragraph < len(paragraphs):
                end = paragraphs[end_paragraph].start
        else:
            start = paragraphs[start_paragraph - 2].end
    return start, end


def _range_label(index: int, start_paragraph: int, end_paragraph: int) -> str:
    return f"replacements[{index}] 的段落范围 {start_paragraph}-{end_paragraph}"


def resolve_paragraph_replacements(content: str, replacements, mode: str = BLANK) -> list[dict]:
    if not replacements:
        raise ValueError("mode=replace 时 replacements 不能为空")
    paragraphs = split_paragraphs(content or "", mode)
    count = len(paragraphs)
    parsed = []
    identical = []
    for index, item in enumerate(replacements):
        start_paragraph = _field(item, "start_paragraph")
        end_paragraph = _field(item, "end_paragraph")
        new = _field(item, "new")
        if not isinstance(start_paragraph, int) or not isinstance(end_paragraph, int):
            raise ValueError(f"replacements[{index}] 的 start_paragraph 和 end_paragraph 必须是整数")
        if not isinstance(new, str):
            raise ValueError(f"replacements[{index}] 的 new 必须是字符串")
        label = _range_label(index, start_paragraph, end_paragraph)
        if start_paragraph < 1 or end_paragraph < 1 or start_paragraph > count or end_paragraph > count:
            raise ValueError(f"{label} 超出有效段落 1-{count}")
        if start_paragraph > end_paragraph:
            raise ValueError(f"{label} 起点大于终点")
        for previous in parsed:
            if start_paragraph <= previous["end_paragraph"] and previous["start_paragraph"] <= end_paragraph:
                raise ValueError(
                    f"{label} 与 {_range_label(previous['index'], previous['start_paragraph'], previous['end_paragraph'])} 重叠"
                )
        start, end = _raw_span(paragraphs, start_paragraph, end_paragraph, new)
        parsed.append({
            "index": index,
            "start_paragraph": start_paragraph,
            "end_paragraph": end_paragraph,
            "start": start,
            "end": end,
            "new": new,
            "is_delete": new == "",
        })
    _separate_adjacent_deletes(parsed, paragraphs)
    for item in parsed:
        old_text = (content or "")[item["start"]:item["end"]]
        item["old_text"] = old_text
        if old_text == item["new"]:
            identical.append(item["index"])
    if identical:
        labels = "、".join(f"第 {index + 1} 条（replacements[{index}]）" for index in identical)
        raise ValueError(
            f"{labels}的新文本与选中原文相同，正文不会发生任何变化。"
            "请把修改后的文字写进 new；不需要修改的片段不要放进 replacements。"
        )
    return parsed


def _separate_adjacent_deletes(items: list[dict], paragraphs: list[Paragraph]) -> None:
    pending = True
    while pending:
        pending = False
        items.sort(key=lambda item: (item["start"], item["end"]))
        for index in range(len(items) - 1):
            previous, current = items[index], items[index + 1]
            if current["start"] >= previous["end"]:
                continue
            if not previous["is_delete"] or not current["is_delete"]:
                raise ValueError(
                    f"{_range_label(current['index'], current['start_paragraph'], current['end_paragraph'])} 与 "
                    f"{_range_label(previous['index'], previous['start_paragraph'], previous['end_paragraph'])} 重叠"
                )
            current["start"] = previous["end"]
            owned_start = paragraphs[current["start_paragraph"] - 1].start
            if current["start"] > owned_start or current["start"] > current["end"]:
                raise ValueError(
                    f"{_range_label(current['index'], current['start_paragraph'], current['end_paragraph'])} 与 "
                    f"{_range_label(previous['index'], previous['start_paragraph'], previous['end_paragraph'])} 重叠"
                )
            pending = True
            if current["start"] == owned_start and current["end_paragraph"] < len(paragraphs):
                following = paragraphs[current["end_paragraph"]].start
                if current["end"] < following:
                    current["end"] = following


def apply_paragraph_replacements(content: str, replacements, mode: str = BLANK) -> tuple[str, list[dict]]:
    resolved = resolve_paragraph_replacements(content, replacements, mode)
    updated = content or ""
    for item in sorted(resolved, key=lambda record: record["start"], reverse=True):
        updated = updated[:item["start"]] + item["new"] + updated[item["end"]:]
    return updated, resolved
