"""豆包 Ark（火山引擎）文生图 API 封装。"""
from pathlib import Path

import httpx
from openai import OpenAI

from config import settings


def generate_and_save(api_key: str, prompt: str, save_path: Path, size: str) -> None:
    client = OpenAI(
        base_url=settings.image_api_base_url,
        api_key=api_key,
    )
    extra_body = {"watermark": settings.image_watermark}
    response = client.images.generate(
        model=settings.image_text2image_model,
        prompt=prompt,
        size=size,
        response_format="url",
        extra_body=extra_body,
    )
    image_url = response.data[0].url
    if not image_url:
        raise RuntimeError("Ark 未返回图片 URL")

    http_resp = httpx.get(image_url, timeout=120)
    http_resp.raise_for_status()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(http_resp.content)
