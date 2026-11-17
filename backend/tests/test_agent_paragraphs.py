"""Agent 段落编号、范围替换和删除分隔符。"""
import hashlib

import pytest

from services.agent_paragraphs import (
    MARKDOWN,
    apply_paragraph_replacements,
    content_reading_view,
    notes_reading_view,
    paragraph_bounds,
    paragraph_index_for_span,
    present_content_record,
    split_paragraphs,
)
from services.chapter_edit_service import build_replacement_diff


def _numbers(content):
    return [(item.number, content[item.start:item.end]) for item in split_paragraphs(content)]


def test_blank_lines_split_paragraphs_and_single_newlines_do_not():
    content = "开头\n仍是第一段\n\n第二段"
    assert _numbers(content) == [(1, "开头\n仍是第一段"), (2, "第二段")]


def test_crlf_whitespace_lines_and_outer_blanks_follow_the_same_rule():
    content = "\r\n\r\n甲\r\n \r\n乙\r\n\r\n\r\n"
    assert _numbers(content) == [(1, "甲"), (2, "乙")]
    assert split_paragraphs("   \n\t\n") == []
    assert split_paragraphs("") == []


def test_multiline_list_without_blank_lines_is_one_paragraph():
    content = "- 甲\n- 乙\n- 丙"
    assert _numbers(content) == [(1, content)]


def test_reading_views_keep_exact_text_and_independent_hashes():
    content = "甲\n\n乙"
    view = content_reading_view(content)
    notes = notes_reading_view(content)
    assert view["content_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert view["content_paragraphs"] == [{"number": 1, "text": "甲"}, {"number": 2, "text": "乙"}]
    assert notes["notes_sha256"] == view["content_sha256"]
    assert notes["notes_paragraphs"] == view["content_paragraphs"]
    assert "1." not in "".join(item["text"] for item in view["content_paragraphs"])


def test_duplicate_paragraphs_replace_only_the_selected_one():
    content = "同样。\n\n同样。"
    updated, resolved = apply_paragraph_replacements(content, [{
        "start_paragraph": 2, "end_paragraph": 2, "new": "改后。",
    }])
    assert updated == "同样。\n\n改后。"
    assert resolved[0]["old_text"] == "同样。"
    assert content.count("同样。") == 2


def test_batch_uses_original_numbers_when_an_earlier_paragraph_grows():
    content = "\n\n".join(f"第{number}段。" for number in range(1, 9))
    updated, _ = apply_paragraph_replacements(content, [
        {"start_paragraph": 8, "end_paragraph": 8, "new": "第8段改。"},
        {"start_paragraph": 2, "end_paragraph": 2, "new": "甲。\n\n乙。\n\n丙。"},
    ])
    assert updated.split("\n\n") == [
        "第1段。", "甲。", "乙。", "丙。", "第3段。", "第4段。", "第5段。", "第6段。", "第7段。", "第8段改。",
    ]


@pytest.mark.parametrize("start,end,new,expected", [
    (2, 2, "第二段改。", "第一段。\n\n第二段改。\n\n第三段。"),
    (2, 3, "合并。", "第一段。\n\n合并。"),
    (2, 2, "第二段。\n\n插入段。", "第一段。\n\n第二段。\n\n插入段。\n\n第三段。"),
    (1, 1, "插入段。\n\n第一段。", "插入段。\n\n第一段。\n\n第二段。\n\n第三段。"),
    (2, 2, "", "第一段。\n\n第三段。"),
    (1, 1, "", "第二段。\n\n第三段。"),
    (3, 3, "", "第一段。\n\n第二段。"),
    (1, 2, "", "第三段。"),
    (2, 3, "", "第一段。"),
])
def test_replace_insert_and_delete_ranges(start, end, new, expected):
    content = "第一段。\n\n第二段。\n\n第三段。"
    updated, _ = apply_paragraph_replacements(content, [{
        "start_paragraph": start, "end_paragraph": end, "new": new,
    }])
    assert updated == expected


def test_separate_adjacent_deletes_leave_one_separator_between_survivors():
    content = "甲。\n\n乙。\n\n丙。\n\n丁。"
    updated, resolved = apply_paragraph_replacements(content, [
        {"start_paragraph": 1, "end_paragraph": 1, "new": ""},
        {"start_paragraph": 2, "end_paragraph": 2, "new": ""},
    ])
    assert updated == "丙。\n\n丁。"
    assert [item["old_text"] for item in sorted(resolved, key=lambda record: record["start"])] == ["甲。\n\n", "乙。\n\n"]


def test_new_text_preserves_quotes_punctuation_backslash_and_markdown():
    content = "原文。"
    new = '他说："路径\\\\图片"，保留。\n\n![图](/a.png)'
    updated, _ = apply_paragraph_replacements(content, [{
        "start_paragraph": 1, "end_paragraph": 1, "new": new,
    }])
    assert updated == new


def test_diff_numbers_follow_the_unified_paragraphs():
    cases = ["甲\n\n\n\n乙", "甲\r\n\r\n乙", "甲\n \n乙"]
    for content in cases:
        assert paragraph_index_for_span(content, split_paragraphs(content)[1].start, "乙") == 2
        _, resolved = apply_paragraph_replacements(content, [{
            "start_paragraph": 2, "end_paragraph": 2, "new": "",
        }])
        assert build_replacement_diff(content, resolved)["hunks"][0]["paragraph_index"] == 2


def test_unmodified_characters_and_outer_blanks_stay_in_place():
    content = "\n\n甲\n\n乙\n\n"
    updated, _ = apply_paragraph_replacements(content, [{
        "start_paragraph": 2, "end_paragraph": 2, "new": "乙改",
    }])
    assert updated == "\n\n甲\n\n乙改\n\n"


@pytest.mark.parametrize("replacements,message", [
    ([{"start_paragraph": 3, "end_paragraph": 3, "new": "越界"}], "超出有效段落"),
    ([{"start_paragraph": 2, "end_paragraph": 1, "new": "倒置"}], "起点大于终点"),
    ([
        {"start_paragraph": 1, "end_paragraph": 2, "new": "甲"},
        {"start_paragraph": 2, "end_paragraph": 2, "new": "乙"},
    ], "重叠"),
    ([{"start_paragraph": 1, "end_paragraph": 1, "new": "甲。"}], "正文不会发生任何变化"),
    ([{"start_paragraph": 1, "end_paragraph": 1, "new": None}], "new 必须是字符串"),
])
def test_invalid_ranges_report_the_item_and_do_not_need_text_search(replacements, message):
    with pytest.raises(ValueError, match=message):
        apply_paragraph_replacements("甲。\n\n甲。", replacements)


PLOT_EXAMPLE = """# 情节一

## 核心事件链
1. **起因·骤然惊醒**：
   - 陆沉从梦中惊醒。
   - 确认距离灾变还有三小时。
2. **高潮·技巧取胜**：
   - 观察后颈硬度。
   - 改砸左膝，借窄缝收杀。"""

PLOT_BLOCKS = [
    "# 情节一",
    "## 核心事件链",
    "1. **起因·骤然惊醒**：",
    "   - 陆沉从梦中惊醒。",
    "   - 确认距离灾变还有三小时。",
    "2. **高潮·技巧取胜**：",
    "   - 观察后颈硬度。",
    "   - 改砸左膝，借窄缝收杀。",
]


def _markdown_texts(content):
    return [content[item.start:item.end] for item in split_paragraphs(content, MARKDOWN)]


def _gaps_are_blank(content):
    paragraphs = split_paragraphs(content, MARKDOWN)
    cursor = 0
    for item in paragraphs:
        assert item.number == paragraphs.index(item) + 1 or item.start >= cursor
        assert item.start >= cursor
        assert content[cursor:item.start].strip(" \t\r\n") == ""
        assert item.start < item.end
        cursor = item.end
    assert content[cursor:].strip(" \t\r\n") == ""
    for index, item in enumerate(paragraphs, 1):
        assert item.number == index
    for left, right in zip(paragraphs, paragraphs[1:]):
        assert left.end <= right.start


def test_plot_example_is_eight_markdown_blocks_and_one_blank_line_tail():
    assert _markdown_texts(PLOT_EXAMPLE) == PLOT_BLOCKS
    assert [item["text"] for item in content_reading_view(PLOT_EXAMPLE, MARKDOWN)["content_paragraphs"]] == PLOT_BLOCKS
    assert [PLOT_EXAMPLE[item.start:item.end] for item in split_paragraphs(PLOT_EXAMPLE)] == [
        "# 情节一",
        PLOT_EXAMPLE.split("\n\n", 1)[1],
    ]
    _gaps_are_blank(PLOT_EXAMPLE)


@pytest.mark.parametrize("content,expected", [
    ("# 标题\n正文", ["# 标题", "正文"]),
    ("开头\n仍是第一段\n\n第二段", ["开头\n仍是第一段", "第二段"]),
    ("- 甲\n- 乙\n- 丙", ["- 甲", "- 乙", "- 丙"]),
    ("- 甲\n\n- 乙", ["- 甲", "- 乙"]),
    ("- parent\n\n  second paragraph\n\n  - child", ["- parent", "  second paragraph", "  - child"]),
    ("- first line\n  still same", ["- first line\n  still same"]),
    ("> 只有一段", ["> 只有一段"]),
    ("| a | b |\n| --- | --- |\n| 1 | 2 |", ["| a | b |\n| --- | --- |\n| 1 | 2 |"]),
    ("```py\n# not a heading\n- not a list\n```", ["```py\n# not a heading\n- not a list\n```"]),
    ("    code line\n    # not heading", ["    code line\n    # not heading"]),
    ("para\n\n---\n\nnext", ["para", "---", "next"]),
    ("![alt](u.png)\n\ntext ![x](y.png) more", ["![alt](u.png)", "text ![x](y.png) more"]),
    ("Title\n=====", ["Title\n====="]),
    ("<div>\n<h1>nope</h1>\n</div>\n\nafter", ["<div>\n<h1>nope</h1>\n</div>", "after"]),
])
def test_markdown_structures_follow_the_block_rules(content, expected):
    assert _markdown_texts(content) == expected
    _gaps_are_blank(content)


def test_blockquote_splits_paragraphs_and_keeps_the_empty_marker_line():
    content = "> para1\n>\n> para2"
    paragraphs = split_paragraphs(content, MARKDOWN)
    assert [content[item.start:item.end] for item in paragraphs] == ["> para1", "> para2"]
    assert content[paragraphs[0].end:paragraphs[1].start] == "\n>\n"


def test_parent_list_blocks_do_not_overlap_or_drop_markers():
    content = "- parent\n\n  second paragraph\n\n  - child"
    paragraphs = split_paragraphs(content, MARKDOWN)
    spans = [(item.start, item.end) for item in paragraphs]
    for index, (start, end) in enumerate(spans):
        for other in spans[index + 1:]:
            assert start >= other[1] or end <= other[0]
    assert content[paragraphs[0].start:paragraphs[0].end].startswith("- parent")
    assert "  - child" == content[paragraphs[2].start:paragraphs[2].end]


def test_markdown_replace_keeps_crlf_and_untouched_characters():
    content = "\r\n\r\n# 标题\r\n\r\n- 甲\r\n- 乙\r\n\r\n"
    assert _markdown_texts(content) == ["# 标题", "- 甲", "- 乙"]
    updated, _ = apply_paragraph_replacements(content, [{
        "start_paragraph": 2, "end_paragraph": 2, "new": "- 甲改",
    }], MARKDOWN)
    assert updated == "\r\n\r\n# 标题\r\n\r\n- 甲改\r\n- 乙\r\n\r\n"


def test_markdown_delete_keeps_a_newline_between_adjacent_items():
    content = "- 甲\n- 乙\n- 丙"
    updated, _ = apply_paragraph_replacements(content, [
        {"start_paragraph": 2, "end_paragraph": 2, "new": ""},
    ], MARKDOWN)
    assert updated == "- 甲\n- 丙"
    loose = "- 甲\n\n- 乙\n\n- 丙"
    updated, _ = apply_paragraph_replacements(loose, [
        {"start_paragraph": 1, "end_paragraph": 1, "new": ""},
        {"start_paragraph": 2, "end_paragraph": 2, "new": ""},
    ], MARKDOWN)
    assert updated == "- 丙"


def test_markdown_batch_keeps_later_numbers_when_an_earlier_item_grows():
    updated, resolved = apply_paragraph_replacements(PLOT_EXAMPLE, [
        {"start_paragraph": 4, "end_paragraph": 4, "new": "   - 陆沉从梦中惊醒。\n   - 先看窗外。"},
        {"start_paragraph": 8, "end_paragraph": 8, "new": "   - 先废双腿，再借窄缝收杀。"},
    ], MARKDOWN)
    assert resolved[1]["old_text"] == "   - 改砸左膝，借窄缝收杀。"
    assert "   - 先看窗外。" in updated
    assert updated.endswith("   - 先废双腿，再借窄缝收杀。")
    assert "   - 观察后颈硬度。" in updated


def test_duplicate_markdown_items_replace_only_the_selected_offset():
    content = "- 同样\n- 同样"
    updated, resolved = apply_paragraph_replacements(content, [{
        "start_paragraph": 2, "end_paragraph": 2, "new": "- 改后",
    }], MARKDOWN)
    assert updated == "- 同样\n- 改后"
    assert paragraph_index_for_span(content, resolved[0]["start"], resolved[0]["old_text"], MARKDOWN) == 2
    assert paragraph_bounds(content, content.rindex("同样"), content.rindex("同样") + 2, MARKDOWN) == (2, 2)
    diff = build_replacement_diff(content, resolved, MARKDOWN)
    assert diff["hunks"][0]["paragraph_index"] == 2
    assert diff["hunks"][0]["start_offset"] == resolved[0]["start"]


def test_segmentation_follows_node_type_and_notes_field():
    listed = "- 甲\n- 乙"
    assert [item["text"] for item in present_content_record({"type": "chapter", "content": listed})["content_paragraphs"]] == [listed]
    assert [item["text"] for item in present_content_record({"type": "note", "content": listed})["content_paragraphs"]] == ["- 甲", "- 乙"]
    assert [item["text"] for item in present_content_record({"type": "chapter_note", "content": listed})["content_paragraphs"]] == ["- 甲", "- 乙"]
    assert [item["text"] for item in notes_reading_view(listed)["notes_paragraphs"]] == ["- 甲", "- 乙"]
    with pytest.raises(ValueError, match="分段模式"):
        present_content_record({"content": listed})
