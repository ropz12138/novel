"""Extraction and structural quality checks for chapter plot highlights."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

PLOT_START = "[[PLOT]]"
PLOT_END = "[[/PLOT]]"
MIN_CHAPTER_CHARS = 400
MIN_HIGHLIGHT_CHARS = 28


@dataclass(frozen=True)
class PlotHighlightValidation:
    valid: bool
    highlights: list[str]
    errors: list[str]
    body_chars: int
    highlighted_chars: int
    required_count: int

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "highlights": self.highlights,
            "errors": self.errors,
            "body_chars": self.body_chars,
            "highlighted_chars": self.highlighted_chars,
            "highlight_count": len(self.highlights),
            "required_count": self.required_count,
        }


def extract_plot_highlights(content: str) -> list[str]:
    return [
        match.strip()
        for match in re.findall(r"\[\[PLOT\]\](.*?)\[\[/PLOT\]\]", content or "", re.DOTALL)
        if match.strip()
    ]


def _visible_chars(text: str) -> int:
    without_markers = text.replace(PLOT_START, "").replace(PLOT_END, "")
    return len(re.sub(r"\s+", "", without_markers))


def _required_highlight_count(body_chars: int) -> int:
    if body_chars < MIN_CHAPTER_CHARS:
        return 0
    return min(6, max(2, math.ceil(body_chars / 1200)))


def validate_plot_highlights(content: str) -> PlotHighlightValidation:
    text = content or ""
    highlights = extract_plot_highlights(text)
    body_chars = _visible_chars(text)
    highlighted_chars = sum(_visible_chars(item) for item in highlights)
    required_count = _required_highlight_count(body_chars)
    errors: list[str] = []

    if text.count(PLOT_START) != text.count(PLOT_END):
        errors.append("剧情高亮标签未成对闭合")

    if required_count and len(highlights) < required_count:
        errors.append(
            f"剧情高亮数量不足：当前 {len(highlights)} 处，"
            f"按正文长度至少需要 {required_count} 处"
        )

    short_indexes = [
        index + 1
        for index, item in enumerate(highlights)
        if _visible_chars(item) < MIN_HIGHLIGHT_CHARS
    ]
    if short_indexes:
        errors.append(
            "以下剧情高亮过短，无法形成完整的“人物-行动/决定-结果”事件句："
            + "、".join(str(index) for index in short_indexes)
        )

    if required_count:
        minimum_summary_chars = max(60, math.ceil(body_chars * 0.04))
        if highlighted_chars < minimum_summary_chars:
            errors.append(
                f"剧情高亮信息量不足：当前 {highlighted_chars} 字，"
                f"至少需要约 {minimum_summary_chars} 字，且应按顺序覆盖本章关键事件链"
            )

    return PlotHighlightValidation(
        valid=not errors,
        highlights=highlights,
        errors=errors,
        body_chars=body_chars,
        highlighted_chars=highlighted_chars,
        required_count=required_count,
    )
