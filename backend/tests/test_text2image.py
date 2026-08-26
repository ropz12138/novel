"""text2image 路由测试 — TDD。"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils import text2image


def test_text2image_routes_to_ark(monkeypatch, tmp_path):
    called = {}

    def fake_ark(api_key, prompt, save_path, size):
        called["provider"] = "ark"
        called["args"] = (api_key, prompt, save_path, size)

    monkeypatch.setattr(text2image.settings, "image_provider", "ark")
    monkeypatch.setattr("utils.ark_image.generate_and_save", fake_ark)

    save_path = tmp_path / "a.png"
    text2image.generate_and_save("key", "中文场景", save_path, "2K")
    assert called["provider"] == "ark"
    assert called["args"] == ("key", "中文场景", save_path, "2K")


def test_text2image_unknown_provider():
    original = text2image.settings.image_provider
    text2image.settings.image_provider = "unknown"
    try:
        with pytest.raises(ValueError, match="不支持的 image.provider"):
            text2image.generate_and_save("k", "中文", Path("/tmp/x.png"), "2K")
    finally:
        text2image.settings.image_provider = original
