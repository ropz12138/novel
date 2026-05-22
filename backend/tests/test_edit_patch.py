"""测试 edit_patch 补丁应用逻辑

验证：
1. 单条 replace 编辑操作
2. 单条 insert 编辑操作
3. 单条 delete 编辑操作
4. 多条编辑操作顺序应用
5. 精确匹配成功
6. 精确匹配失败时模糊匹配成功
7. 模糊匹配也失败时回退到全文输出
8. edits 为空时回退
9. search 为空时回退
10. 同一位置多次匹配时选择最佳匹配
11. build_hunk_diff: 精确 hunk diff 生成
12. build_hunk_diff: 字符级高亮
13. build_hunk_diff: context 折叠
"""

import pytest

from app.services.supervisor.edit_patch import (
    apply_edits,
    PatchResult,
    EditOperation,
    build_hunk_diff,
)


# ── 测试用正文 ──

SAMPLE_CONTENT = (
    "林远站在窗前，望着远处的山峦。夕阳将天空染成了一片金红，"
    "微风吹过他的脸颊，带来一丝凉意。\n"
    "他想起多年前的事，那时候他还只是个少年。"
    "父亲常对他说：'路还很长，别急。'\n"
    "如今父亲已经不在了，但那句话却一直留在他心中。"
    "林远握紧了拳头，眼神变得坚定。"
)


# ────────────────────────── 1. replace 操作 ──────────────────────────


class TestReplaceEdit:
    """验证 replace 类型编辑操作"""

    def test_replace_single_exact_match(self):
        """精确匹配替换"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夕阳将天边烧成了绚烂的火红",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "绚烂的火红" in result.content
        assert "一片金红" not in result.content
        # 未被修改的部分应保持不变
        assert "林远站在窗前" in result.content

    def test_replace_preserves_surrounding(self):
        """替换不影响周围文本"""
        edits = [
            EditOperation(
                type="replace",
                search="微风吹过他的脸颊，带来一丝凉意。",
                content="寒风掠过他的脸庞，刺骨的冷。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "夕阳将天空染成了一片金红" in result.content
        assert "寒风掠过他的脸庞" in result.content
        assert "微风吹过他的脸颊" not in result.content

    def test_replace_multiline(self):
        """跨行替换"""
        content = "第一行内容\n第二行内容\n第三行内容"
        edits = [
            EditOperation(
                type="replace",
                search="第一行内容\n第二行内容",
                content="新的第一行\n新的第二行",
            )
        ]
        result = apply_edits(content, edits)
        assert result.success is True
        assert "新的第一行" in result.content
        assert "第三行内容" in result.content

    def test_replace_with_empty_content(self):
        """替换为空内容（等同于删除）"""
        edits = [
            EditOperation(
                type="replace",
                search="微风吹过他的脸颊，带来一丝凉意。",
                content="",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "微风吹过他的脸颊" not in result.content


# ────────────────────────── 2. insert 操作 ──────────────────────────


class TestInsertEdit:
    """验证 insert 类型编辑操作"""

    def test_insert_after_anchor(self):
        """在锚定文本之后插入新内容"""
        edits = [
            EditOperation(
                type="insert",
                after="带来一丝凉意。",
                content="\n他深深地吸了一口气，空气中带着泥土的芬芳。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "空气中带着泥土的芬芳" in result.content
        # 原文不变
        assert "带来一丝凉意。" in result.content

    def test_insert_at_beginning(self):
        """在文本最开头插入"""
        edits = [
            EditOperation(
                type="insert",
                after="",
                content="序幕\n\n",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert result.content.startswith("序幕")

    def test_insert_anchor_not_found(self):
        """insert 的 after 未找到时应回退"""
        edits = [
            EditOperation(
                type="insert",
                after="这段文本完全不存在于正文中",
                content="不应该被插入的内容",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is False
        assert "不应该被插入的内容" not in result.content


# ────────────────────────── 3. delete 操作 ──────────────────────────


class TestDeleteEdit:
    """验证 delete 类型编辑操作"""

    def test_delete_exact_match(self):
        """精确匹配删除"""
        edits = [
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "微风吹过他的脸颊" not in result.content
        assert "林远站在窗前" in result.content

    def test_delete_only_match(self):
        """删除文本后前后应自然连接"""
        content = "ABCD删除这段EFGH"
        edits = [
            EditOperation(
                type="delete",
                search="删除这段",
            )
        ]
        result = apply_edits(content, edits)
        assert result.success is True
        assert result.content == "ABCDEFGH"


# ────────────────────────── 4. 多条编辑操作 ──────────────────────────


class TestMultipleEdits:
    """验证多条编辑操作顺序应用"""

    def test_two_replace_edits(self):
        """两条不重叠的替换操作"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夕阳将天边烧成了绚烂的火红",
            ),
            EditOperation(
                type="replace",
                search="林远握紧了拳头",
                content="林远缓缓松开了拳头",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "绚烂的火红" in result.content
        assert "缓缓松开了拳头" in result.content
        assert "一片金红" not in result.content
        assert "握紧了拳头" not in result.content

    def test_mixed_edit_types(self):
        """混合使用 replace、insert、delete"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临，星星开始闪烁",
            ),
            EditOperation(
                type="insert",
                after="眼神变得坚定。",
                content="\n他知道，新的旅程即将开始。",
            ),
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "星星开始闪烁" in result.content
        assert "新的旅程即将开始" in result.content
        assert "微风吹过他的脸颊" not in result.content

    def test_edits_applied_in_order(self):
        """编辑应按给定顺序应用"""
        content = "AAAA"
        edits = [
            EditOperation(type="replace", search="AAAA", content="BBBB"),
            EditOperation(type="replace", search="BBBB", content="CCCC"),
        ]
        result = apply_edits(content, edits)
        assert result.success is True
        assert result.content == "CCCC"

    def test_overlapping_edits_first_wins(self):
        """重叠编辑：先应用的先生效，后续如果匹配失败则跳过"""
        content = "ABCDEFGHIJ"
        edits = [
            EditOperation(type="replace", search="BCDEFG", content="XYZ"),
            EditOperation(type="replace", search="BCDEFG", content="ZZZ"),
        ]
        result = apply_edits(content, edits)
        assert result.success is True
        assert "XYZ" in result.content
        # 第二条 BCDEFG 已不存在，应被跳过
        assert "ZZZ" not in result.content


# ────────────────────────── 5. 模糊匹配 ──────────────────────────


class TestFuzzyMatch:
    """验证精确匹配失败时的模糊匹配"""

    def test_fuzzy_match_minor_diff(self):
        """search 有少量字符差异时模糊匹配应成功"""
        edits = [
            EditOperation(
                type="replace",
                # 和原文差了一个标点：原文是 "。"，这里是 "."
                search="微风吹过他的脸颊，带来一丝凉意.",
                content="寒风掠过他的脸庞。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "寒风掠过他的脸庞" in result.content

    def test_fuzzy_match_extra_whitespace(self):
        """search 有额外空格时模糊匹配应成功"""
        edits = [
            EditOperation(
                type="replace",
                search="林远站在窗前， 望着远处的山峦。",
                content="林远伫立在窗前，凝视着远方的群山。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "凝视着远方的群山" in result.content


# ────────────────────────── 6. 回退机制 ──────────────────────────


class TestFallback:
    """验证所有编辑都无法匹配时的回退"""

    def test_all_edits_fail_returns_original(self):
        """所有编辑都匹配失败时，返回原文并标记失败"""
        edits = [
            EditOperation(
                type="replace",
                search="这段文本完全不存在",
                content="新的内容",
            ),
            EditOperation(
                type="delete",
                search="另一段不存在的文本",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is False
        assert result.content == SAMPLE_CONTENT

    def test_empty_edits_returns_original(self):
        """空编辑列表返回原文并标记失败"""
        result = apply_edits(SAMPLE_CONTENT, [])
        assert result.success is False
        assert result.content == SAMPLE_CONTENT

    def test_partial_success_still_applies(self):
        """部分编辑成功、部分失败时，成功的仍然生效"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临，星星开始闪烁",
            ),
            EditOperation(
                type="replace",
                search="完全不存在的内容",
                content="不应出现",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert "星星开始闪烁" in result.content
        assert "不应出现" not in result.content
        # 至少有一条失败的记录
        assert len(result.failed_edits) > 0


# ────────────────────────── 7. 边界情况 ──────────────────────────


class TestEdgeCases:
    """验证边界情况"""

    def test_empty_original_content(self):
        """原文为空"""
        edits = [
            EditOperation(
                type="insert",
                after="",
                content="新增的内容",
            )
        ]
        result = apply_edits("", edits)
        assert result.success is True
        assert result.content == "新增的内容"

    def test_replace_entire_content(self):
        """替换整个原文"""
        edits = [
            EditOperation(
                type="replace",
                search=SAMPLE_CONTENT,
                content="全新的内容。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert result.content == "全新的内容。"

    def test_search_too_short_rejected(self):
        """search 片段太短（< 10字符）应被拒绝并回退"""
        edits = [
            EditOperation(
                type="replace",
                search="林远",
                content="张三",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        # search 太短，不应匹配
        assert "张三" not in result.content

    def test_result_contains_applied_count(self):
        """结果应包含成功应用的编辑数"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临",
            ),
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        assert result.success is True
        assert result.applied_count == 2


# ────────────────────────── 8. Hunk Diff 生成 ──────────────────────────


class TestHunkDiffReplace:
    """验证 replace 操作的 hunk diff 生成"""

    def test_replace_produces_hunk(self):
        """replace 应产生一个 hunk，包含 removed + added"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夕阳将天边烧成了绚烂的火红",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk["type"] == "replace"
        assert "removed" in hunk
        assert "added" in hunk
        assert "夕阳将天空染成了一片金红" in hunk["removed"]
        assert "夕阳将天边烧成了绚烂的火红" in hunk["added"]

    def test_replace_has_context(self):
        """replace 的 hunk 应包含前后上下文"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夕阳将天边烧成了绚烂的火红",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        hunk = hunks[0]
        assert "context_before" in hunk
        assert "context_after" in hunk
        # 上下文应包含周围文本
        assert "望着远处的山峦" in hunk["context_before"]
        assert "微风吹过他的脸颊" in hunk["context_after"]

    def test_replace_has_char_diff(self):
        """replace 的 hunk 应包含字符级差异高亮"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夕阳将天边烧成了绚烂的火红",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        hunk = hunks[0]
        # 应有 char_diff 字段，标记字符级别的变化
        assert "char_diff" in hunk
        char_diff = hunk["char_diff"]
        assert "removed_segments" in char_diff
        assert "added_segments" in char_diff


class TestHunkDiffInsert:
    """验证 insert 操作的 hunk diff 生成"""

    def test_insert_produces_hunk(self):
        """insert 应产生一个 hunk，只有 added"""
        edits = [
            EditOperation(
                type="insert",
                after="带来一丝凉意。",
                content="\n他深深地吸了一口气。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk["type"] == "insert"
        assert hunk["added"] == "\n他深深地吸了一口气。"
        assert hunk["removed"] == ""
        assert "context_before" in hunk

    def test_insert_at_beginning_no_context_before(self):
        """在开头插入时 context_before 应为空"""
        edits = [
            EditOperation(
                type="insert",
                after="",
                content="序幕\n",
            )
        ]
        result = apply_edits("", edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 1
        assert hunks[0]["context_before"] == ""


class TestHunkDiffDelete:
    """验证 delete 操作的 hunk diff 生成"""

    def test_delete_produces_hunk(self):
        """delete 应产生一个 hunk，只有 removed"""
        edits = [
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk["type"] == "delete"
        assert hunk["removed"] == "微风吹过他的脸颊，带来一丝凉意。"
        assert hunk["added"] == ""


class TestHunkDiffMultiple:
    """验证多条编辑的 hunk diff"""

    def test_multiple_edits_produce_multiple_hunks(self):
        """多条编辑应产生多个 hunk"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临",
            ),
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 2

    def test_failed_edits_not_in_hunks(self):
        """失败的编辑不应产生 hunk"""
        edits = [
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临",
            ),
            EditOperation(
                type="replace",
                search="完全不存在的内容",
                content="不应出现",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 1

    def test_hunks_ordered_by_position(self):
        """hunks 应按在原文中的位置排序"""
        edits = [
            EditOperation(
                type="replace",
                search="林远握紧了拳头，眼神变得坚定。",
                content="林远缓缓松开了拳头。",
            ),
            EditOperation(
                type="replace",
                search="夕阳将天空染成了一片金红",
                content="夜幕降临",
            ),
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert len(hunks) == 2
        # 第一个 hunk 应在原文更前面的位置
        assert hunks[0]["old_start"] < hunks[1]["old_start"]

    def test_no_successful_edits_empty_hunks(self):
        """没有成功编辑时 hunks 为空"""
        edits = [
            EditOperation(
                type="replace",
                search="完全不存在的内容",
                content="新的内容",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert hunks == []


class TestHunkDiffCharLevel:
    """验证字符级差异高亮"""

    def test_char_diff_segments(self):
        """字符级差异应将文本分为不变/changed 片段"""
        edits = [
            EditOperation(
                type="replace",
                search="他想起多年前的事",
                content="他回想起很多年前的事",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        hunk = hunks[0]
        char_diff = hunk["char_diff"]

        # removed_segments 和 added_segments 都是列表
        # 每个元素是 {"text": "...", "changed": true/false}
        removed_segs = char_diff["removed_segments"]
        added_segs = char_diff["added_segments"]

        # added 侧应该有 changed 的片段（新增了"回"和"很"）
        assert any(s["changed"] for s in added_segs)
        # 开头 "他" 应该是 unchanged
        assert removed_segs[0]["text"] == "他"
        assert not removed_segs[0]["changed"]

    def test_char_diff_identical_text(self):
        """replace 内容完全相同时，所有片段都是 unchanged"""
        edits = [
            EditOperation(
                type="replace",
                search="他想起多年前的事",
                content="他想起多年前的事",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        hunk = hunks[0]
        char_diff = hunk["char_diff"]
        assert all(not s["changed"] for s in char_diff["removed_segments"])
        assert all(not s["changed"] for s in char_diff["added_segments"])

    def test_delete_no_char_diff(self):
        """delete 操作不需要字符级 diff"""
        edits = [
            EditOperation(
                type="delete",
                search="微风吹过他的脸颊，带来一丝凉意。",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        # delete 不应有 char_diff（整段删除无需细粒度高亮）
        assert "char_diff" not in hunks[0] or hunks[0].get("char_diff") is None

    def test_insert_no_char_diff(self):
        """insert 操作不需要字符级 diff"""
        edits = [
            EditOperation(
                type="insert",
                after="带来一丝凉意。",
                content="新内容",
            )
        ]
        result = apply_edits(SAMPLE_CONTENT, edits)
        hunks = build_hunk_diff(result)
        assert "char_diff" not in hunks[0] or hunks[0].get("char_diff") is None
