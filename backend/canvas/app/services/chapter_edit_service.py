"""章节正文局部编辑：段落级校验、apply 与 diff 生成。"""
from __future__ import annotations

from app.services.chapter_illustration_service import split_paragraphs


def validate_edits(edits: list[dict], paragraphs: list[str]) -> list[str]:
    """校验 edits 列表；返回错误信息列表，空列表表示通过。"""
    errors: list[str] = []
    if not edits:
        errors.append("edits 不能为空")
        return errors

    for i, edit in enumerate(edits):
        edit_type = edit.get("type")
        idx = edit.get("paragraph_index")

        if edit_type not in ("replace", "insert_after", "delete"):
            errors.append(f"edits[{i}] 未知 type: {edit_type}")
            continue

        if idx is None or not isinstance(idx, int):
            errors.append(f"edits[{i}] 缺少有效的 paragraph_index")
            continue

        if edit_type == "insert_after":
            if idx < 0 or idx > len(paragraphs):
                errors.append(
                    f"edits[{i}] insert_after paragraph_index={idx} 超出范围 0..{len(paragraphs)}"
                )
            new_text = edit.get("new_text", "")
            if not str(new_text).strip():
                errors.append(f"edits[{i}] insert_after 缺少 new_text")
            continue

        if idx < 1 or idx > len(paragraphs):
            errors.append(
                f"edits[{i}] paragraph_index={idx} 超出段落数 {len(paragraphs)}"
            )
            continue

        paragraph = paragraphs[idx - 1]
        old_text = edit.get("old_text", "")

        if edit_type == "replace":
            new_text = edit.get("new_text", "")
            if not str(old_text):
                errors.append(f"edits[{i}] replace 缺少 old_text")
            elif old_text not in paragraph:
                errors.append(f"edits[{i}] 段落 {idx} 中未找到 old_text")
            elif not str(new_text).strip() and old_text == paragraph:
                errors.append(f"edits[{i}] replace 缺少 new_text")
        elif edit_type == "delete":
            if old_text != paragraph:
                errors.append(f"edits[{i}] delete 的 old_text 必须与段落 {idx} 全文完全一致")

    return errors


def _apply_single_edit(paragraphs: list[str], edit: dict) -> list[str]:
    edit_type = edit["type"]
    idx = edit["paragraph_index"]
    result = list(paragraphs)

    if edit_type == "insert_after":
        pos = idx
        result.insert(pos, edit["new_text"])
        return result

    pos = idx - 1
    paragraph = result[pos]

    if edit_type == "replace":
        old_text = edit["old_text"]
        new_text = edit["new_text"]
        if old_text == paragraph:
            result[pos] = new_text
        else:
            result[pos] = paragraph.replace(old_text, new_text, 1)
    elif edit_type == "delete":
        del result[pos]

    return result


def apply_edits(content: str, edits: list[dict]) -> str:
    """按段落 apply edits；多 edits 时从高 paragraph_index 到低依次 apply，避免索引偏移。"""
    paragraphs = split_paragraphs(content)
    errors = validate_edits(edits, paragraphs)
    if errors:
        raise ValueError(errors[0])

    ordered = sorted(
        edits,
        key=lambda e: (
            e.get("paragraph_index", 0),
            {"delete": 0, "replace": 1, "insert_after": 2}.get(e.get("type"), 3),
        ),
        reverse=True,
    )

    current = paragraphs
    for edit in ordered:
        current = _apply_single_edit(current, edit)

    if not current:
        return ""
    return "\n\n".join(current)


def build_chapter_edit_diff(old_content: str, new_content: str, edits: list[dict]) -> dict:
    """根据 edits 构建段落级 diff（canvas 原生格式）。"""
    hunks: list[dict] = []
    chars_added = 0
    chars_removed = 0

    for edit in edits:
        edit_type = edit["type"]
        hunk: dict = {
            "type": edit_type,
            "paragraph_index": edit["paragraph_index"],
        }

        if edit_type == "replace":
            old_text = edit.get("old_text", "")
            new_text = edit.get("new_text", "")
            hunk["old_text"] = old_text
            hunk["new_text"] = new_text
            chars_removed += len(old_text)
            chars_added += len(new_text)
        elif edit_type == "insert_after":
            new_text = edit.get("new_text", "")
            hunk["new_text"] = new_text
            hunk["old_text"] = ""
            chars_added += len(new_text)
        elif edit_type == "delete":
            old_text = edit.get("old_text", "")
            hunk["old_text"] = old_text
            hunk["new_text"] = ""
            chars_removed += len(old_text)

        hunks.append(hunk)

    hunks.sort(key=lambda h: h["paragraph_index"])

    return {
        "hunks": hunks,
        "summary": {
            "paragraphs_changed": len(hunks),
            "chars_added": chars_added,
            "chars_removed": chars_removed,
            "content_changed": old_content != new_content,
        },
    }
