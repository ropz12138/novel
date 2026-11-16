"""有声小说 TTS：普通 MiMo、VoiceDesign 与讯飞离线引擎。"""
from contextlib import aclosing

import httpx
from starlette.concurrency import run_in_threadpool

from config import settings
from services.llm.llm_service import BaseLLMProvider
from services.llm.llm_types import LLMModelConfig


async def stream_speech(text: str):
    if settings.tts_provider == "iflytek_xtts":
        from services.xtts_engine import synthesize_speech
        yield await run_in_threadpool(synthesize_speech, text)
        return

    if settings.tts_provider == "mimo_voicedesign":
        audio = {"format": "pcm16", "optimize_text_preview": False}
        instruction = settings.tts_voice_description
    else:
        audio = {"format": "pcm16", "voice": settings.tts_mimo_voice}
        instruction = settings.tts_style
    provider = BaseLLMProvider(LLMModelConfig(
        name=f"audiobook-{settings.tts_provider}",
        provider="openai",
        base_url=settings.tts_mimo_base_url,
        api_key=settings.tts_mimo_api_key,
        model=settings.tts_mimo_model,
        extra_body={"audio": audio},
    ))
    messages = [
        {"role": "user", "content": instruction},
        {"role": "assistant", "content": text},
    ]
    size = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.tts_timeout_seconds, connect=10)) as client:
        async with aclosing(provider.stream_audio(messages, client=client)) as chunks:
            async for pcm in chunks:
                size += len(pcm)
                yield pcm
    if not size or size % 2:
        raise ValueError("MiMo 返回的 PCM 音频为空或不完整")
