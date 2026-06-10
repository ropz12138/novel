"""Diff 服务 — 大纲/角色变更对比与摘要

提供三个核心能力：
1. compute_outline_diff：对比新旧 outline_tree，生成结构化变更列表
2. compute_character_diff：对比新旧角色列表，生成角色变更列表
3. summarize_outline_diff / summarize_character_diff：变更摘要统计
"""

from __future__ import annotations

import copy
from typing import Any


# ── 大纲 diff ──


def compute_outline_diff(old: dict, new: dict) -> dict:
    """对比新旧 outline_tree，生成按子结构分类的变更列表。

    Returns:
        {
            "story": [StoryFieldChange, ...],
            "macro_phases": [MacroPhaseChange, ...],
            "meso_stages": [MesoStageChange, ...],
            "foreshadowing": [ForeshadowingChange, ...],
        }
    """
    return {
        "story": _diff_story(old.get("story", {}), new.get("story", {})),
        "macro_phases": _diff_node_list(
            old.get("outline", {}).get("macro_phases", []),
            new.get("outline", {}).get("macro_phases", []),
        ),
        "meso_stages": _diff_node_list(
            old.get("meso", {}).get("meso_stages", []),
            new.get("meso", {}).get("meso_stages", []),
        ),
        "foreshadowing": _diff_node_list(old.get("foreshadowing", []), new.get("foreshadowing", [])),
    }


def _diff_story(old_story: dict, new_story: dict) -> list[dict]:
    """对比 story 字段级别的变更"""
    changes = []
    all_keys = set(list(old_story.keys()) + list(new_story.keys()))
    for key in sorted(all_keys):
        old_val = old_story.get(key)
        new_val = new_story.get(key)
        if key not in old_story:
            changes.append({"type": "added", "field": key, "old": None, "new": new_val})
        elif key not in new_story:
            changes.append({"type": "removed", "field": key, "old": old_val, "new": None})
        elif old_val != new_val:
            changes.append({"type": "modified", "field": key, "old": old_val, "new": new_val})
    return changes


def _diff_node_list(old_nodes: list[dict], new_nodes: list[dict]) -> list[dict]:
    """对比节点列表（timeline/branches/foreshadowing）

    匹配策略：按 node id 匹配。
    """
    old_by_id = {n.get("id"): n for n in old_nodes}
    new_by_id = {n.get("id"): n for n in new_nodes}

    all_ids = list(dict.fromkeys(list(old_by_id.keys()) + list(new_by_id.keys())))
    changes = []

    for node_id in all_ids:
        old_node = old_by_id.get(node_id)
        new_node = new_by_id.get(node_id)

        if old_node is None and new_node is not None:
            changes.append({"type": "added", "node_id": node_id, "data": copy.deepcopy(new_node)})
        elif old_node is not None and new_node is None:
            changes.append({"type": "removed", "node_id": node_id, "data": copy.deepcopy(old_node)})
        elif old_node is not None and new_node is not None:
            field_changes = _diff_node_fields(old_node, new_node)
            if field_changes:
                changes.append({"type": "modified", "node_id": node_id, "changes": field_changes})

    return changes


def _diff_node_fields(old_node: dict, new_node: dict) -> list[dict]:
    """对比单个节点的字段变更（排除 id 字段）"""
    changes = []
    all_keys = set(list(old_node.keys()) + list(new_node.keys()))
    for key in sorted(all_keys):
        if key == "id":
            continue
        old_val = old_node.get(key)
        new_val = new_node.get(key)
        if key not in old_node:
            changes.append({"type": "added", "field": key, "old": None, "new": new_val})
        elif key not in new_node:
            changes.append({"type": "removed", "field": key, "old": old_val, "new": None})
        elif old_val != new_val:
            changes.append({"type": "modified", "field": key, "old": old_val, "new": new_val})
    return changes


# ── 角色 diff ──


def compute_character_diff(old: list[dict], new: list[dict]) -> dict:
    """对比新旧角色列表，生成角色变更列表。

    匹配策略：按 name 字段匹配。

    Returns:
        {
            "changes": [
                {"type": "added", "name": str, "data": dict},
                {"type": "removed", "name": str, "data": dict},
                {"type": "modified", "name": str, "changes": [FieldChange, ...]},
            ]
        }
    """
    old_by_name = {c.get("name"): c for c in old}
    new_by_name = {c.get("name"): c for c in new}

    all_names = list(dict.fromkeys(list(old_by_name.keys()) + list(new_by_name.keys())))
    changes = []

    for name in all_names:
        old_char = old_by_name.get(name)
        new_char = new_by_name.get(name)

        if old_char is None and new_char is not None:
            changes.append({"type": "added", "name": name, "data": copy.deepcopy(new_char)})
        elif old_char is not None and new_char is None:
            changes.append({"type": "removed", "name": name, "data": copy.deepcopy(old_char)})
        elif old_char is not None and new_char is not None:
            field_changes = _diff_node_fields(old_char, new_char)
            if field_changes:
                changes.append({"type": "modified", "name": name, "changes": field_changes})

    return {"changes": changes}


# ── 摘要统计 ──


def summarize_outline_diff(diff: dict) -> dict:
    """统计大纲 diff 摘要"""
    added = 0
    modified = 0
    removed = 0

    for item in diff.get("story", []):
        t = item.get("type")
        if t == "added":
            added += 1
        elif t == "modified":
            modified += 1
        elif t == "removed":
            removed += 1

    for section in ("macro_phases", "meso_stages", "foreshadowing"):
        for item in diff.get(section, []):
            t = item.get("type")
            if t == "added":
                added += 1
            elif t == "modified":
                modified += 1
            elif t == "removed":
                removed += 1

    return {
        "total_added": added,
        "total_modified": modified,
        "total_removed": removed,
        "total_changes": added + modified + removed,
    }


def summarize_character_diff(diff: dict) -> dict:
    """统计角色 diff 摘要"""
    added = 0
    modified = 0
    removed = 0

    for item in diff.get("changes", []):
        t = item.get("type")
        if t == "added":
            added += 1
        elif t == "modified":
            modified += 1
        elif t == "removed":
            removed += 1

    return {
        "total_added": added,
        "total_modified": modified,
        "total_removed": removed,
        "total_changes": added + modified + removed,
    }
