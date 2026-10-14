"""局部编辑以工具提交的替换项为分组，保留完整文本及字符位置。"""
import pytest

from services.chapter_edit_service import build_replacement_diff
from services.agent_diff_groups import apply_groups, compose_groups


def test_inserted_dialogue_and_edited_tail_remain_one_agent_group():
    original = "前文。\n\n孙教授说。\n\n陆沉没有立即答应。\n\n后文。"
    old = "孙教授说。\n\n陆沉没有立即答应。"
    new = "孙教授说。\n\n新增对白一。\n\n新增对白二。\n\n陆沉没有接话。"
    result = build_replacement_diff(original, [{"old": old, "new": new}])
    assert result["grouping"] == "agent_replacements"
    assert result["hunks"] == [{
        "type": "replace", "paragraph_index": 2,
        "start_offset": len("前文。\n\n"), "old_text": old, "new_text": new,
    }]


def test_each_submitted_item_is_a_group_in_execution_order():
    result = build_replacement_diff("😀甲旧，乙旧。", [
        {"old": "乙旧", "new": "乙新"},
        {"old": "甲旧", "new": "甲新且更长"},
    ])
    assert [h["old_text"] for h in result["hunks"]] == ["乙旧", "甲旧"]
    assert [h["start_offset"] for h in result["hunks"]] == [4, 1]


def test_deletion_preserves_exact_newlines():
    result = build_replacement_diff("甲。\n\n乙。\n\n丙。", [{"old": "乙。\n\n", "new": ""}])
    assert result["hunks"][0]["old_text"] == "乙。\n\n"
    assert result["hunks"][0]["type"] == "delete"


@pytest.mark.parametrize("old", ["不存在", "重复"])
def test_invalid_old_is_rejected(old):
    with pytest.raises(ValueError):
        build_replacement_diff("重复重复", [{"old": old, "new": "新"}])


def test_composition_keeps_disjoint_agent_groups_and_merges_exact_overlap():
    baseline = "甲旧。\n\n乙旧。"
    first = build_replacement_diff(baseline, [{"old": "甲旧", "new": "甲新"}])
    groups = compose_groups(baseline, [], first["hunks"])
    current = apply_groups(baseline, groups)
    second = build_replacement_diff(current, [{"old": "乙旧", "new": "乙新"}])
    groups = compose_groups(baseline, groups, second["hunks"])
    assert [(g["old_text"], g["new_text"]) for g in groups] == [("甲旧", "甲新"), ("乙旧", "乙新")]
    third = build_replacement_diff(apply_groups(baseline, groups), [{"old": "甲新", "new": "甲再改"}])
    groups = compose_groups(baseline, groups, third["hunks"])
    assert [(g["old_text"], g["new_text"]) for g in groups] == [("甲旧", "甲再改"), ("乙旧", "乙新")]
    assert apply_groups(baseline, groups) == "甲再改。\n\n乙新。"


def test_composition_preserves_multiline_group_and_partial_change_inside_it():
    baseline = "前文。\n\nA\n\nB\n\n后文。"
    first = build_replacement_diff(baseline, [{"old": "A\n\nB", "new": "X\n\nA′\n\nB′"}])
    groups = compose_groups(baseline, [], first["hunks"])
    second = build_replacement_diff(apply_groups(baseline, groups), [{"old": "B′", "new": "B″"}])
    groups = compose_groups(baseline, groups, second["hunks"])
    assert len(groups) == 1
    assert groups[0]["old_text"] == "A\n\nB"
    assert groups[0]["new_text"] == "X\n\nA′\n\nB″"


def test_composition_tracks_insertions_deletions_and_exact_reversion():
    baseline = "甲。\n\n乙。"
    groups = compose_groups(baseline, [], [{"start_offset": 0, "old_text": "甲。\n\n", "new_text": ""}])
    assert apply_groups(baseline, groups) == "乙。"
    groups = compose_groups(baseline, groups, [{"start_offset": 1, "old_text": "。", "new_text": "新。"}])
    assert apply_groups(baseline, groups) == "乙新。"
    groups = compose_groups("甲", [], [{"start_offset": 0, "old_text": "甲", "new_text": "乙"},
                                          {"start_offset": 0, "old_text": "乙", "new_text": "甲"}])
    assert groups == []


def test_insertion_inside_existing_group_stays_in_that_group():
    groups = compose_groups("甲旧", [], [{"start_offset": 0, "old_text": "甲旧", "new_text": "甲新"}])
    groups = compose_groups("甲旧", groups, [{"start_offset": 1, "old_text": "", "new_text": "手改"}])
    assert len(groups) == 1
    assert apply_groups("甲旧", groups) == "甲手改新"


def test_restoring_deleted_content_clears_the_pending_diff():
    groups = compose_groups("甲", [], [{"start_offset": 0, "old_text": "甲", "new_text": ""}])
    assert compose_groups("甲", groups, [{"start_offset": 0, "old_text": "", "new_text": "甲"}]) == []
