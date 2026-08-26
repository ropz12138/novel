"""豆包 Ark 文生图封装测试 — TDD。"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from utils import ark_image


class _FakeImage:
    def __init__(self, url: str):
        self.url = url


class _FakeResponse:
    def __init__(self, url: str):
        self.data = [_FakeImage(url)]


def test_ark_generate_and_save_downloads_image(tmp_path, monkeypatch):
    save_path = tmp_path / "out.png"
    fake_png = b"\x89PNG\r\n\x1a\n" + b"ark-image"

    mock_client = MagicMock()
    mock_client.images.generate.return_value = _FakeResponse("https://example.com/a.png")

    def fake_get(url, timeout=60):
        assert url == "https://example.com/a.png"
        response = httpx.Response(200, content=fake_png, request=httpx.Request("GET", url))
        return response

    monkeypatch.setattr(ark_image.httpx, "get", fake_get)

    with patch.object(ark_image, "OpenAI", return_value=mock_client):
        ark_image.generate_and_save(
            "test-key",
            "图书馆对峙场景，冷色调",
            save_path,
            "2K",
        )

    mock_client.images.generate.assert_called_once()
    call_kwargs = mock_client.images.generate.call_args.kwargs
    assert call_kwargs["model"]
    assert call_kwargs["prompt"] == "图书馆对峙场景，冷色调"
    assert call_kwargs["size"] == "2K"
    assert call_kwargs["response_format"] == "url"
    assert call_kwargs["extra_body"] == {"watermark": True}
    assert save_path.read_bytes() == fake_png
