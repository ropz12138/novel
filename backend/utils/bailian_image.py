"""百炼（DashScope）文生图 API 封装。"""
import time
from pathlib import Path

import httpx

from config import settings


def _image_create_url() -> str:
    base = settings.image_api_base_url.rstrip("/")
    return f"{base}/services/aigc/text2image/image-synthesis"


def _task_base_url() -> str:
    base = settings.image_api_base_url.rstrip("/")
    return f"{base}/tasks"


def get_api_key() -> str:
    key = settings.image_api_key or ""
    if not key:
        raise ValueError("请在 config.json 中配置 image.api_key")
    return key


def create_task(api_key: str, prompt: str, size: str) -> str:
    resp = httpx.post(
        _image_create_url(),
        headers={
            "X-DashScope-Async": "enable",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.image_text2image_model,
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("output", {}).get("task_id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"未返回 task_id，响应: {data}")
    return task_id


def poll_task_result(
    api_key: str,
    task_id: str,
    poll_interval: float = 4,
    max_wait: float = 300,
) -> dict:
    url = f"{_task_base_url()}/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {})
        status = output.get("task_status") or data.get("task_status") or output.get("status")
        if status == "SUCCEEDED":
            return output
        if status == "FAILED":
            msg = output.get("message") or data.get("message") or "任务失败"
            raise RuntimeError(f"任务失败: {msg}")
        time.sleep(poll_interval)
    raise RuntimeError("轮询超时，未在限定时间内完成")


def get_image_url_from_output(output: dict) -> str:
    results = output.get("results") or output.get("output_image_list") or []
    if not results:
        raise RuntimeError(f"output 中无图片结果: {output}")
    first = results[0] if isinstance(results[0], dict) else {"url": results[0]}
    url = first.get("url") or first.get("image_url")
    if not url:
        raise RuntimeError(f"无法解析图片 URL: {first}")
    return url


def download_image(url: str, save_path: Path) -> None:
    resp = httpx.get(url, timeout=60)
    resp.raise_for_status()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(resp.content)


def generate_and_save(api_key: str, prompt: str, save_path: Path, size: str) -> None:
    task_id = create_task(api_key, prompt, size=size)
    output = poll_task_result(api_key, task_id)
    image_url = get_image_url_from_output(output)
    download_image(image_url, save_path)
