"""edit_patch — 局部补丁编辑引擎

提供基于 search/replace/insert/delete 的局部编辑能力，
替代全量正文输出，节省 token 消耗。

核心数据结构：
- EditOperation: 单条编辑指令（replace / insert / delete）
- PatchResult: 应用编辑后的结果
- AppliedHunk: 单条成功编辑的位置信息

核心函数：
- apply_edits: 将一组 EditOperation 应用到原文上，返回 PatchResult
- build_hunk_diff: 从 PatchResult 中提取精确的 hunk diff（含字符级高亮）
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# search 片段最小长度：低于此阈值视为不可靠，拒绝匹配
MIN_SEARCH_LENGTH = 4

# 模糊匹配相似度阈值
FUZZY_RATIO_THRESHOLD = 0.75

# 用于模糊匹配时，在原文中切取候选片段的额外扩展字符数
FUZZY_CONTEXT_MARGIN = 30

# build_hunk_diff 的上下文字符数
HUNK_CONTEXT_CHARS = 60


# ── 数据结构 ──


@dataclass
class EditOperation:
    """单条编辑操作"""

    type: Literal["replace", "insert", "delete"]
    # replace/delete 的定位锚定文本
    search: str = ""
    # insert 的定位锚定文本（在此文本之后插入）
    after: str = ""
    # replace/insert 的新内容
    content: str = ""


@dataclass
class AppliedHunk:
    """单条成功编辑的位置信息"""

    edit_type: str  # "replace" / "insert" / "delete"
    # 该编辑在**当前文本快照**中的操作位置
    old_start: int
    old_end: int  # 被替换/删除的文本范围
    removed_text: str  # 被替换/删除的原文片段
    added_text: str  # 插入/替换的新内容


@dataclass
class PatchResult:
    """apply_edits 的返回值"""

    # 应用编辑后的完整正文
    content: str
    # 是否至少成功应用了一条编辑
    success: bool = False
    # 成功应用的编辑条数
    applied_count: int = 0
    # 失败的编辑及其原因
    failed_edits: list[dict] = field(default_factory=list)
    # 成功编辑的位置信息（供 build_hunk_diff 使用）
    hunks: list[AppliedHunk] = field(default_factory=list)


# ── 内部匹配函数 ──


def _exact_match(text: str, search: str) -> int | None:
    """精确匹配，返回 search 在 text 中的起始位置，未找到返回 None"""
    idx = text.find(search)
    return idx if idx != -1 else None


def _fuzzy_match(text: str, search: str) -> tuple[int, int] | None:
    """模糊匹配：在 text 中寻找与 search 最相似的片段。

    返回 (start, end) 表示最佳匹配范围，未找到返回 None。
    策略：以 search 长度为窗口在 text 上滑动，计算 SequenceMatcher 相似度。
    """
    search_len = len(search)
    best_ratio = 0.0
    best_pos = None

    # 步长：根据文本长度自适应，避免全文扫描太慢
    step = max(1, search_len // 4)

    for start in range(0, len(text) - search_len + 1, step):
        end = start + search_len
        candidate = text[start:end]
        ratio = difflib.SequenceMatcher(None, search, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_pos = (start, end)

    # 在最佳位置附近做精细扫描
    if best_pos and best_ratio >= FUZZY_RATIO_THRESHOLD * 0.9:
        coarse_start = best_pos[0]
        refine_start = max(0, coarse_start - FUZZY_CONTEXT_MARGIN)
        refine_end = min(len(text), coarse_start + search_len + FUZZY_CONTEXT_MARGIN)

        for start in range(refine_start, refine_end):
            end = min(len(text), start + search_len)
            if end - start < MIN_SEARCH_LENGTH:
                continue
            candidate = text[start:end]
            ratio = difflib.SequenceMatcher(None, search, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = (start, end)

    if best_pos and best_ratio >= FUZZY_RATIO_THRESHOLD:
        return best_pos
    return None


def _find_match(text: str, search: str) -> tuple[int, int] | None:
    """先精确匹配，失败后模糊匹配。返回 (start, end) 或 None。"""
    # 检查 search 最小长度
    if len(search.strip()) < MIN_SEARCH_LENGTH:
        return None

    # 1. 精确匹配
    idx = _exact_match(text, search)
    if idx is not None:
        return (idx, idx + len(search))

    # 2. 模糊匹配
    return _fuzzy_match(text, search)


# ── 单条编辑应用 ──


def _apply_single_edit(text: str, edit: EditOperation) -> tuple[str, bool]:
    """应用单条编辑到文本上。返回 (新文本, 是否成功)。"""
    new_text, ok, _ = _apply_single_edit_with_hunk(text, edit)
    return new_text, ok


def _apply_single_edit_with_hunk(
    text: str, edit: EditOperation
) -> tuple[str, bool, AppliedHunk | None]:
    """应用单条编辑，同时返回位置信息。返回 (新文本, 是否成功, hunk)。"""
    if edit.type == "replace":
        match = _find_match(text, edit.search)
        if match is None:
            return text, False, None
        start, end = match
        hunk = AppliedHunk(
            edit_type="replace",
            old_start=start,
            old_end=end,
            removed_text=text[start:end],
            added_text=edit.content,
        )
        return text[:start] + edit.content + text[end:], True, hunk

    elif edit.type == "insert":
        if edit.after == "":
            hunk = AppliedHunk(
                edit_type="insert",
                old_start=0,
                old_end=0,
                removed_text="",
                added_text=edit.content,
            )
            return edit.content + text, True, hunk
        match = _find_match(text, edit.after)
        if match is None:
            return text, False, None
        _, end = match
        hunk = AppliedHunk(
            edit_type="insert",
            old_start=end,
            old_end=end,
            removed_text="",
            added_text=edit.content,
        )
        return text[:end] + edit.content + text[end:], True, hunk

    elif edit.type == "delete":
        match = _find_match(text, edit.search)
        if match is None:
            return text, False, None
        start, end = match
        hunk = AppliedHunk(
            edit_type="delete",
            old_start=start,
            old_end=end,
            removed_text=text[start:end],
            added_text="",
        )
        return text[:start] + text[end:], True, hunk

    else:
        logger.warning("未知的编辑类型: %s", edit.type)
        return text, False, None


# ── 主入口 ──


def apply_edits(original: str, edits: list[EditOperation]) -> PatchResult:
    """将一组编辑操作应用到原文上。

    策略：
    1. 按 edits 顺序逐条应用
    2. 每条编辑先精确匹配，失败则模糊匹配
    3. 所有编辑都失败时返回原文并标记 success=False
    4. 至少一条成功即标记 success=True
    """
    if not edits:
        return PatchResult(content=original, success=False)

    current = original
    applied_count = 0
    failed_edits: list[dict] = []
    hunks: list[AppliedHunk] = []

    for i, edit in enumerate(edits):
        new_text, ok, hunk = _apply_single_edit_with_hunk(current, edit)
        if ok:
            current = new_text
            applied_count += 1
            if hunk:
                hunks.append(hunk)
        else:
            failed_edits.append({
                "index": i,
                "type": edit.type,
                "search": edit.search[:100] if edit.search else (edit.after[:100] if edit.after else ""),
                "reason": "未找到匹配位置",
            })

    success = applied_count > 0
    return PatchResult(
        content=current,
        success=success,
        applied_count=applied_count,
        failed_edits=failed_edits,
        hunks=hunks,
    )


# ── Hunk Diff 构建 ──


def _build_char_diff(old: str, new: str) -> dict:
    """对两段文本做字符级 diff，返回前端可直接渲染的片段列表。

    返回：
    {
        "removed_segments": [{"text": "...", "changed": true/false}, ...],
        "added_segments": [{"text": "...", "changed": true/false}, ...]
    }
    """
    sm = difflib.SequenceMatcher(None, old, new)
    removed_segments: list[dict] = []
    added_segments: list[dict] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            removed_segments.append({"text": old[i1:i2], "changed": False})
            added_segments.append({"text": new[j1:j2], "changed": False})
        elif tag == "replace":
            removed_segments.append({"text": old[i1:i2], "changed": True})
            added_segments.append({"text": new[j1:j2], "changed": True})
        elif tag == "delete":
            removed_segments.append({"text": old[i1:i2], "changed": True})
        elif tag == "insert":
            added_segments.append({"text": new[j1:j2], "changed": True})

    return {
        "removed_segments": removed_segments,
        "added_segments": added_segments,
    }


def build_hunk_diff(result: PatchResult, original: str = "") -> list[dict]:
    """从 PatchResult 中构建精确的 hunk diff 列表。

    每个 hunk 包含：
    - type: "replace" / "insert" / "delete"
    - removed: 被替换/删除的原文片段
    - added: 插入/替换的新内容
    - context_before: 修改位置前的上下文
    - context_after: 修改位置后的上下文
    - old_start / old_end: 在原文中的位置
    - char_diff: 字符级差异（仅 replace 类型）
    """
    if not result.hunks:
        return []

    # 如果未传入 original，从 result 反推不了原始上下文
    # 此时不带 context
    source = original if original else result.content

    # 按 old_start 排序
    sorted_hunks = sorted(result.hunks, key=lambda h: h.old_start)

    hunks_data: list[dict] = []
    for hunk in sorted_hunks:
        entry: dict = {
            "type": hunk.edit_type,
            "removed": hunk.removed_text,
            "added": hunk.added_text,
            "old_start": hunk.old_start,
            "old_end": hunk.old_end,
            "context_before": "",
            "context_after": "",
        }

        # 计算上下文
        if source:
            ctx_start = max(0, hunk.old_start - HUNK_CONTEXT_CHARS)
            entry["context_before"] = source[ctx_start:hunk.old_start]

            ctx_end = min(len(source), hunk.old_end + HUNK_CONTEXT_CHARS)
            entry["context_after"] = source[hunk.old_end:ctx_end]

        # 字符级 diff（仅 replace）
        if hunk.edit_type == "replace" and hunk.removed_text and hunk.added_text:
            entry["char_diff"] = _build_char_diff(hunk.removed_text, hunk.added_text)

        hunks_data.append(entry)

    return hunks_data
