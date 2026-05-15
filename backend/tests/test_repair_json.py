"""Tests for _repair_unquoted_values and _repair_trailing_commas.

TDD: These tests should FAIL before the fix and PASS after.
"""
import time
import pytest
import sys
sys.path.insert(0, "/root/Novel/backend")

from app.services.work_service import _repair_unquoted_values, _repair_trailing_commas


class TestRepairUnquotedValues:
    """_repair_unquoted_values should wrap bare (non-JSON) values in quotes."""

    def test_chinese_bare_values(self):
        """Chinese bare values should be quoted in ONE pass."""
        blob = '{"title": 末日黎明, "genre": 科幻}'
        result = _repair_unquoted_values(blob)
        assert '"title": "末日黎明"' in result
        assert '"genre": "科幻"' in result

    def test_chinese_with_punctuation(self):
        blob = '{"age": ？（外表约四十）, "name": 张三}'
        result = _repair_unquoted_values(blob)
        assert '"age": "？（外表约四十）"' in result
        assert '"name": "张三"' in result

    def test_mixed_chinese_and_ascii(self):
        blob = '{"desc": some text without quotes, "type": 普通}'
        result = _repair_unquoted_values(blob)
        assert '"desc": "some text without quotes"' in result
        assert '"type": "普通"' in result

    def test_already_quoted_values_unchanged(self):
        """Already-quoted values must NOT be double-quoted."""
        blob = '{"title": "末日黎明", "genre": "科幻"}'
        result = _repair_unquoted_values(blob)
        assert result == blob

    def test_numeric_values_unchanged(self):
        blob = '{"count": 42, "ratio": 3.14}'
        result = _repair_unquoted_values(blob)
        assert result == blob

    def test_boolean_null_unchanged(self):
        blob = '{"active": true, "deleted": false, "data": null}'
        result = _repair_unquoted_values(blob)
        assert result == blob

    def test_convergence_speed(self):
        """Must complete within 1 second even for worst-case input."""
        blob = '{"title": 末日黎明, "genre": 科幻末日, "volume": 第一卷}'
        t0 = time.time()
        result = _repair_unquoted_values(blob)
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"_repair_unquoted_values took {elapsed:.2f}s — likely infinite loop"

    def test_nested_object_bare_values(self):
        blob = '{"story": {"title": 末日黎明, "genre": 科幻}, "type": 普通}'
        result = _repair_unquoted_values(blob)
        assert '"title": "末日黎明"' in result
        assert '"genre": "科幻"' in result


class TestRepairTrailingCommas:
    """_repair_trailing_commas should remove trailing commas before } or ]."""

    def test_basic_trailing_comma_object(self):
        blob = '{"a": 1, "b": 2,}'
        assert _repair_trailing_commas(blob) == '{"a": 1, "b": 2}'

    def test_basic_trailing_comma_array(self):
        blob = '[1, 2, 3,]'
        assert _repair_trailing_commas(blob) == '[1, 2, 3]'

    def test_no_trailing_comma(self):
        blob = '{"a": 1, "b": 2}'
        assert _repair_trailing_commas(blob) == blob

    def test_convergence(self):
        """Must terminate."""
        blob = '{"a": 1, "b": {"c": 2,},}'
        result = _repair_trailing_commas(blob)
        assert ",}" not in result
        assert ",]" not in result
