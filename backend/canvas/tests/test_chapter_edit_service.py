"""chapter_edit_service 单元测试 — TDD。"""
import pytest

from app.services.chapter_edit_service import (
    apply_edits,
    build_chapter_edit_diff,
    split_paragraphs,
    validate_edits,
)


SAMPLE = "第一段内容。\n\n第二段内容。\n\n第三段内容。"


def test_split_paragraphs():
    parts = split_paragraphs(SAMPLE)
    assert len(parts) == 3
    assert parts[0] == "第一段内容。"


def test_validate_replace_success():
    edits = [{
        "type": "replace",
        "paragraph_index": 2,
        "old_text": "第二段内容。",
        "new_text": "第二段改写了。",
    }]
    assert validate_edits(edits, split_paragraphs(SAMPLE)) == []


def test_validate_replace_old_text_not_found():
    edits = [{
        "type": "replace",
        "paragraph_index": 2,
        "old_text": "不存在",
        "new_text": "新",
    }]
    errors = validate_edits(edits, split_paragraphs(SAMPLE))
    assert len(errors) == 1
    assert "未找到" in errors[0]


def test_validate_delete_requires_full_paragraph():
    edits = [{
        "type": "delete",
        "paragraph_index": 1,
        "old_text": "第一段",
    }]
    errors = validate_edits(edits, split_paragraphs(SAMPLE))
    assert len(errors) == 1


def test_validate_insert_after_zero():
    edits = [{"type": "insert_after", "paragraph_index": 0, "new_text": "文首段。"}]
    assert validate_edits(edits, split_paragraphs(SAMPLE)) == []


def test_apply_replace_only_changes_target():
    edits = [{
        "type": "replace",
        "paragraph_index": 2,
        "old_text": "第二段内容。",
        "new_text": "第二段改写了。",
    }]
    new_content = apply_edits(SAMPLE, edits)
    parts = split_paragraphs(new_content)
    assert parts[0] == "第一段内容。"
    assert parts[1] == "第二段改写了。"
    assert parts[2] == "第三段内容。"


def test_apply_insert_after():
    edits = [{"type": "insert_after", "paragraph_index": 1, "new_text": "插入段。"}]
    new_content = apply_edits(SAMPLE, edits)
    parts = split_paragraphs(new_content)
    assert len(parts) == 4
    assert parts[1] == "插入段。"


def test_apply_delete():
    edits = [{
        "type": "delete",
        "paragraph_index": 2,
        "old_text": "第二段内容。",
    }]
    new_content = apply_edits(SAMPLE, edits)
    parts = split_paragraphs(new_content)
    assert len(parts) == 2
    assert "第二段" not in new_content


def test_build_chapter_edit_diff_summary():
    edits = [{
        "type": "replace",
        "paragraph_index": 2,
        "old_text": "第二段内容。",
        "new_text": "第二段改写了。",
    }]
    new_content = apply_edits(SAMPLE, edits)
    diff = build_chapter_edit_diff(SAMPLE, new_content, edits)
    assert len(diff["hunks"]) == 1
    assert diff["hunks"][0]["type"] == "replace"
    assert diff["summary"]["paragraphs_changed"] == 1
    assert diff["summary"]["chars_removed"] == len("第二段内容。")
    assert diff["summary"]["chars_added"] == len("第二段改写了。")


def test_apply_multiple_edits_reverse_order():
    edits = [
        {
            "type": "replace",
            "paragraph_index": 3,
            "old_text": "第三段内容。",
            "new_text": "第三段新。",
        },
        {
            "type": "replace",
            "paragraph_index": 1,
            "old_text": "第一段内容。",
            "new_text": "第一段新。",
        },
    ]
    new_content = apply_edits(SAMPLE, edits)
    parts = split_paragraphs(new_content)
    assert parts[0] == "第一段新。"
    assert parts[2] == "第三段新。"
