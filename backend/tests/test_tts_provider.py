"""普通 MiMo TTS 增量输出、取消及讯飞配置切换。"""
import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from config import Settings
from services.llm.llm_service import BaseLLMProvider
from services.llm.llm_types import LLMModelConfig


def _settings(provider='mimo_tts'):
    return SimpleNamespace(
        tts_provider=provider, tts_sample_rate=16000 if provider == 'iflytek_xtts' else 24000,
        tts_mimo_base_url='https://mimo.test/v1', tts_mimo_api_key='test-key',
        tts_mimo_model='mimo-v2.5-tts', tts_mimo_voice='茉莉',
        tts_style='用温柔自然的语气讲述故事。', tts_timeout_seconds=180,
        tts_voice_description='温柔清澈的年轻女性，语速舒缓。',
    )


def _sse(pcm):
    data = {'choices': [{'delta': {'audio': {'data': base64.b64encode(pcm).decode()}}}]}
    return ('data: ' + json.dumps(data) + '\n\n').encode()


def test_mimo_streams_first_audio_before_upstream_finishes(monkeypatch):
    from services.tts import stream_speech
    monkeypatch.setattr('services.tts.settings', _settings())
    text = '正文完整保留。' * 2000
    requests = []
    closed = []

    async def run():
        release = asyncio.Event()
        class AudioStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield _sse(b'\x01\x00')
                await release.wait()
                yield _sse(b'\x02\x00')
                yield b'data: [DONE]\n\n'
            async def aclose(self):
                closed.append(True)
        def handle(request):
            requests.append(json.loads(request.content))
            assert request.headers['authorization'] == 'Bearer test-key'
            return httpx.Response(200, stream=AudioStream())
        original = BaseLLMProvider.stream_audio
        async def stream_audio(self, messages, **kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                async for pcm in original(self, messages, client=client):
                    yield pcm
        monkeypatch.setattr(BaseLLMProvider, 'stream_audio', stream_audio)
        stream = stream_speech(text)
        assert await asyncio.wait_for(anext(stream), 2) == b'\x01\x00'
        assert not release.is_set()
        release.set()
        assert [part async for part in stream] == [b'\x02\x00']
    asyncio.run(run())
    assert closed == [True]
    payload = requests[0]
    assert payload['model'] == 'mimo-v2.5-tts'
    assert payload['stream'] is True
    assert payload['audio'] == {'format': 'pcm16', 'voice': '茉莉'}
    assert payload['messages'] == [
        {'role': 'user', 'content': '用温柔自然的语气讲述故事。'},
        {'role': 'assistant', 'content': text},
    ]
    assert 'max_tokens' not in payload
    assert 'max_completion_tokens' not in payload


def test_base_audio_stream_closes_upstream_when_consumer_stops():
    closed = []
    class AudioStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _sse(b'\x01\x00')
            await asyncio.Event().wait()
        async def aclose(self):
            closed.append(True)
    async def run():
        provider = BaseLLMProvider(LLMModelConfig(
            name='tts-test', base_url='https://mimo.test/v1', api_key='key',
            provider='openai', model='mimo-v2.5-tts',
        ))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=AudioStream()))) as client:
            stream = provider.stream_audio([{'role': 'assistant', 'content': '正文'}], client=client)
            assert await anext(stream) == b'\x01\x00'
            await stream.aclose()
            assert closed == [True]
    asyncio.run(run())


def test_iflytek_selection_preserves_original_engine(monkeypatch):
    from services.tts import stream_speech
    monkeypatch.setattr('services.tts.settings', _settings('iflytek_xtts'))
    calls = []
    monkeypatch.setattr('services.xtts_engine.synthesize_speech', lambda text: calls.append(text) or b'\x01\x00')
    async def run():
        return [part async for part in stream_speech('原来的声音')]
    assert asyncio.run(run()) == [b'\x01\x00']
    assert calls == ['原来的声音']


@pytest.mark.parametrize('parts', [[], [b'\x01']])
def test_empty_or_incomplete_mimo_audio_is_rejected(monkeypatch, parts):
    from services.tts import stream_speech
    monkeypatch.setattr('services.tts.settings', _settings())
    async def stream_audio(*args, **kwargs):
        for part in parts:
            yield part
    monkeypatch.setattr(BaseLLMProvider, 'stream_audio', stream_audio)
    async def run():
        return [part async for part in stream_speech('正文')]
    with pytest.raises(ValueError):
        asyncio.run(run())


def test_mimo_errors_do_not_switch_to_iflytek(monkeypatch):
    from services.tts import stream_speech
    monkeypatch.setattr('services.tts.settings', _settings())
    async def failed(*args, **kwargs):
        raise RuntimeError('MiMo unavailable')
        yield
    monkeypatch.setattr(BaseLLMProvider, 'stream_audio', failed)
    monkeypatch.setattr('services.xtts_engine.synthesize_speech', lambda text: pytest.fail('unexpected fallback'))
    async def run():
        return [part async for part in stream_speech('正文')]
    with pytest.raises(RuntimeError, match='MiMo unavailable'):
        asyncio.run(run())


def test_tts_settings_switch_rate_without_rewriting_iflytek_config():
    settings = Settings.__new__(Settings)
    tts = {
        'provider': 'mimo_tts',
        'mimo_tts': {
            'base_url': 'https://tts.test/v1', 'api_key': 'tts-key',
            'model': 'mimo-v2.5-tts', 'voice': '茉莉', 'style': '温柔自然',
            'timeout_seconds': 180, 'audio_format': 'pcm', 'sample_rate': 24000,
        },
        'mimo_voicedesign': {
            'base_url': 'https://design.test/v1', 'api_key': 'design-key',
            'model': 'mimo-v2.5-tts-voicedesign', 'voice_description': '清澈女声',
            'timeout_seconds': 90, 'audio_format': 'pcm', 'sample_rate': 24000,
        },
        'iflytek_xtts': {
            'sdk_dir': 'backend/vendor/iflytek_xtts', 'app_id': 'app', 'api_key': 'old-key',
            'api_secret': 'secret', 'vcn': 'xiaoyan', 'language': 1,
            'audio_format': 'pcm', 'sample_rate': 16000,
        },
    }
    settings._parse_tts_config(tts)
    assert settings.tts_sample_rate == 24000
    assert settings.tts_mimo_voice == '茉莉'
    assert settings.tts_mimo_api_key == 'tts-key'
    assert settings.tts_mimo_base_url == 'https://tts.test/v1'
    tts['provider'] = 'mimo_voicedesign'
    settings._parse_tts_config(tts)
    assert settings.tts_sample_rate == 24000
    assert settings.tts_mimo_model == 'mimo-v2.5-tts-voicedesign'
    assert settings.tts_voice_description == '清澈女声'
    assert settings.tts_mimo_api_key == 'design-key'
    assert settings.tts_mimo_base_url == 'https://design.test/v1'
    assert settings.tts_timeout_seconds == 90
    tts['provider'] = 'iflytek_xtts'
    settings._parse_tts_config(tts)
    assert settings.tts_sample_rate == 16000
    assert settings.tts_api_key == 'old-key'
    assert settings.tts_vcn == 'xiaoyan'
    from config import PROJECT_ROOT
    assert settings.tts_sdk_dir == str(PROJECT_ROOT / 'backend/vendor/iflytek_xtts')
    tts['provider'] = 'typo'
    with pytest.raises(ValueError, match='tts.provider'):
        settings._parse_tts_config(tts)


def test_voicedesign_uses_base_audio_api_without_rewriting_or_truncating_text(monkeypatch):
    from services.tts import stream_speech
    config = _settings('mimo_voicedesign')
    config.tts_mimo_model = 'mimo-v2.5-tts-voicedesign'
    monkeypatch.setattr('services.tts.settings', config)
    requests = []
    text = '完整的小说正文。' * 2000
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=_sse(b'\x01\x00\x02\x00') + b'data: [DONE]\n\n')
    original = BaseLLMProvider.stream_audio
    async def stream_audio(self, messages, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            async for pcm in original(self, messages, client=client):
                yield pcm
    monkeypatch.setattr(BaseLLMProvider, 'stream_audio', stream_audio)
    async def run():
        return [pcm async for pcm in stream_speech(text)]
    assert asyncio.run(run()) == [b'\x01\x00\x02\x00']
    payload = requests[0]
    assert payload['model'] == 'mimo-v2.5-tts-voicedesign'
    assert payload['audio'] == {'format': 'pcm16', 'optimize_text_preview': False}
    assert payload['messages'] == [
        {'role': 'user', 'content': '温柔清澈的年轻女性，语速舒缓。'},
        {'role': 'assistant', 'content': text},
    ]
    assert 'max_tokens' not in payload
    assert 'max_completion_tokens' not in payload


@pytest.mark.parametrize('provider,rate', [('mimo_tts', 24000), ('mimo_voicedesign', 24000), ('iflytek_xtts', 16000)])
def test_tts_only_reads_selected_independent_profile(provider, rate):
    profile = {
        'audio_format': 'pcm', 'sample_rate': rate,
        'base_url': 'https://selected.test/v1', 'api_key': 'selected-key',
        'model': 'selected-model', 'voice': '茉莉', 'style': '温柔',
        'voice_description': '清澈女声', 'timeout_seconds': 120,
        'sdk_dir': 'backend/vendor/iflytek_xtts', 'app_id': 'app',
        'api_secret': 'secret', 'vcn': 'xiaoyan', 'language': 1,
    }
    settings = Settings.__new__(Settings)
    settings._parse_tts_config({'provider': provider, provider: profile})
    assert settings.tts_sample_rate == rate
    if provider == 'iflytek_xtts':
        assert settings.tts_api_key == 'selected-key'
    else:
        assert settings.tts_mimo_api_key == 'selected-key'
