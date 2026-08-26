"""文生图 API 统一入口，按 config.image.provider 路由。"""
from pathlib import Path

from config import settings


def get_api_key() -> str:
    key = settings.image_api_key or ""
    if not key:
        raise ValueError("请在 config.json 中配置 image.api_key")
    return key


def generate_and_save(api_key: str, prompt: str, save_path: Path, size: str | None = None) -> None:
    effective_size = size or settings.chapter_illustration_size
    provider = settings.image_provider
    if provider == "ark":
        from utils.ark_image import generate_and_save as ark_generate_and_save

        ark_generate_and_save(api_key, prompt, save_path, effective_size)
        return
    if provider == "dashscope":
        from utils.bailian_image import generate_and_save as dashscope_generate_and_save

        dashscope_generate_and_save(api_key, prompt, save_path, effective_size)
        return
    raise ValueError(f"不支持的 image.provider: {provider}")
