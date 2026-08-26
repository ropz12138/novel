"""章节正文插图 Markdown 插入逻辑 — TDD。"""
import pytest

from config import PROJECT_ROOT
from services.chapter_illustration_service import (
    CHAPTER_ILLUSTRATION_STYLE_SUFFIX,
    ILLUSTRATIONS_DIR,
    build_full_prompt,
    build_illustration_markdown,
    illustration_file_path,
    insert_illustration_into_content,
    validate_chinese_prompt,
)


def test_project_root_is_repo_root():
    assert (PROJECT_ROOT / "backend" / "config.py").is_file()
    assert (PROJECT_ROOT / "frontend").is_dir()


def test_illustrations_dir_is_under_data():
    assert ILLUSTRATIONS_DIR == PROJECT_ROOT / "data" / "illustrations"


def test_illustration_file_path_is_under_data():
    path = illustration_file_path("work-1", "illus-1")
    assert path == PROJECT_ROOT / "data" / "illustrations" / "work-1" / "illus-1.png"


def test_build_illustration_markdown():
    md = build_illustration_markdown("abc-123")
    assert md == "![章节插画](/api/illustrations/abc-123)"


def test_insert_after_first_paragraph():
    content = "第一段。\n\n第二段。\n\n第三段。"
    md = build_illustration_markdown("id-2")
    result = insert_illustration_into_content(content, 1, md)
    parts = result.split("\n\n")
    assert parts[0] == "第一段。"
    assert parts[1] == md
    assert parts[2] == "第二段。"
    assert parts[3] == "第三段。"


def test_rejects_insert_before_any_text():
    content = "第一段。\n\n第二段。"
    md = build_illustration_markdown("id-1")
    with pytest.raises(ValueError, match="禁止插在正文最前"):
        insert_illustration_into_content(content, 0, md)


def test_insert_at_end():
    content = "第一段。\n\n第二段。"
    md = build_illustration_markdown("id-3")
    result = insert_illustration_into_content(content, -1, md)
    assert result.endswith(md)
    assert result.index("第一段。") < result.index(md)


def test_insert_into_empty_content():
    md = build_illustration_markdown("id-4")
    with pytest.raises(ValueError, match="禁止插在正文最前"):
        insert_illustration_into_content("", 0, md)
    assert insert_illustration_into_content("", -1, md) == md


def test_insert_after_paragraph_out_of_range():
    content = "只有一段。"
    md = build_illustration_markdown("id-5")
    with pytest.raises(ValueError, match="超出段落数"):
        insert_illustration_into_content(content, 2, md)


def test_build_full_prompt_requires_chinese():
    result = build_full_prompt("高中走廊，丧尸扑向学生，荧光灯闪烁，恐怖氛围")
    assert "高中走廊" in result
    assert CHAPTER_ILLUSTRATION_STYLE_SUFFIX in result


def test_build_full_prompt_rejects_english_only():
    with pytest.raises(ValueError, match="必须使用中文"):
        build_full_prompt("A chaotic high school corridor scene with zombies")


def test_validate_chinese_prompt_accepts_mixed_with_names():
    validate_chinese_prompt("林远在教学楼大厅用灭火器击打丧尸保安，阳光从玻璃门照入")
