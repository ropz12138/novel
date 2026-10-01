"""Token 用量：兼容各模型 usage 并汇总缓存输入、未缓存输入与输出。"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import database
from config import settings
from main import app
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user
from services.agents.supervisor import reset_context, set_context
from services.llm.llm_service import OpenAILLMClient
from services.llm.llm_types import LLMModelConfig
from services.token_usage import parse_openai_token_usage, record_openai_usage, summarize_token_usage

client = TestClient(app)


def _cfg(name: str) -> LLMModelConfig:
    return LLMModelConfig(
        name=name,
        base_url="http://example.test/v1",
        api_key="k",
        provider="openai",
        model=name,
    )


class _JsonResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.content = b"{}"
        self.text = ""

    def json(self):
        return self._body


class _SyncClient:
    def __init__(self, body: dict):
        self.body = body

    def post(self, *args, **kwargs):
        return _JsonResponse(self.body)

    def close(self):
        return None


class _FakeStreamResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.status_code = 200
        self.is_success = True
        self.request = type("Req", (), {"url": "http://example.test/v1/chat/completions"})()

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _FakeAsyncClient:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.stream_kwargs = None

    def stream(self, *args, **kwargs):
        self.stream_kwargs = kwargs
        return _FakeStreamResponse(self._lines)

    async def aclose(self):
        return None


@pytest.fixture
def auth_user():
    db = database.SessionLocal()
    try:
        user = User(username="tester", email="usage@t.t", password_hash="x", role="admin")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def test_parse_glm_and_mimo_splits_cached_from_prompt_tokens():
    usage = {
        "completion_tokens": 10,
        "prompt_tokens": 18,
        "prompt_tokens_details": {"cached_tokens": 4},
        "total_tokens": 28,
    }
    assert parse_openai_token_usage(usage) == (4, 14, 10)


def test_user_cannot_access_token_usage(auth_user):
    auth_user.role = "user"
    assert client.get("/api/token-usage").status_code == 403


def test_parse_deepseek_uses_explicit_cache_hit_and_miss():
    usage = {
        "prompt_tokens": 9,
        "completion_tokens": 1,
        "total_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 0},
        "prompt_cache_hit_tokens": 2,
        "prompt_cache_miss_tokens": 7,
    }
    assert parse_openai_token_usage(usage) == (2, 7, 1)


def test_parse_gpt_without_cache_details_counts_all_prompt_tokens_as_uncached():
    usage = {
        "prompt_tokens": 16210,
        "completion_tokens": 26,
        "total_tokens": 16236,
        "completion_tokens_details": {"reasoning_tokens": 17},
    }
    assert parse_openai_token_usage(usage) == (0, 16210, 26)


def test_parse_qwen_splits_cached_tokens_from_prompt_tokens():
    usage = {
        "prompt_tokens": 3019,
        "completion_tokens": 104,
        "total_tokens": 3123,
        "prompt_tokens_details": {"cached_tokens": 2048},
    }
    assert parse_openai_token_usage(usage) == (2048, 971, 104)


def test_parse_returns_none_when_required_token_totals_are_missing():
    assert parse_openai_token_usage({"completion_tokens": 1, "total_tokens": 8}) is None
    assert parse_openai_token_usage(None) is None


def test_complete_records_configured_model_usage():
    model = settings.available_models[0]
    llm = OpenAILLMClient(_cfg(model))
    text = llm.complete(
        [{"role": "user", "content": "hi"}],
        client=_SyncClient({
            "choices": [{"message": {"content": "好"}}],
            "usage": {
                "completion_tokens": 10,
                "prompt_tokens": 18,
                "prompt_tokens_details": {"cached_tokens": 5},
            },
        }),
    )
    assert text == "好"
    rows = summarize_token_usage()
    recorded = next(row for row in rows if row["model"] == model)
    assert recorded["cached_input_tokens"] == 5
    assert recorded["uncached_input_tokens"] == 13
    assert recorded["output_tokens"] == 10


def test_stream_records_usage_from_terminal_chunk():
    model = settings.available_models[1]
    llm = OpenAILLMClient(_cfg(model))
    fake_client = _FakeAsyncClient([
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        'data: {"choices":[],"usage":{"completion_tokens":3,"prompt_tokens":13,"prompt_tokens_details":{"cached_tokens":0}}}',
        "data: [DONE]",
    ])

    async def _run():
        events = [
            event
            async for event in llm.stream_chat(
                [{"role": "user", "content": "hi"}],
                client=fake_client,
            )
        ]
        return events

    events = asyncio.run(_run())
    assert fake_client.stream_kwargs["json"]["stream_options"] == {"include_usage": True}
    assert [event.text for event in events if event.kind == "text"] == ["好"]
    recorded = next(row for row in summarize_token_usage() if row["model"] == model)
    assert recorded["model"] == model
    assert recorded["cached_input_tokens"] == 0
    assert recorded["uncached_input_tokens"] == 13
    assert recorded["output_tokens"] == 3
    assert recorded["cached_input_percent"] == 0.0
    assert "average_time_to_first_token_ms" in recorded
    assert "average_output_tokens_per_second" in recorded
    assert "latest_time_to_first_token_ms" in recorded
    assert "latest_output_tokens_per_second" in recorded


def test_record_usage_persists_latency_and_summarizes_model_speed():
    from models.llm_token_usage import LlmTokenUsage

    model = settings.available_models[0]
    record_openai_usage(
        model,
        {"completion_tokens": 30, "prompt_tokens": 12},
        time_to_first_token_ms=250,
        generation_duration_ms=1500,
        request_duration_ms=1800,
    )
    record_openai_usage(
        model,
        {"completion_tokens": 10, "prompt_tokens": 8},
        time_to_first_token_ms=750,
        generation_duration_ms=500,
        request_duration_ms=1300,
    )

    with database.SessionLocal() as db:
        rows = (
            db.query(LlmTokenUsage)
            .filter(LlmTokenUsage.model_name == model)
            .order_by(LlmTokenUsage.created_at.asc())
            .all()
        )
        assert [row.time_to_first_token_ms for row in rows] == [250, 750]
        assert [row.generation_duration_ms for row in rows] == [1500, 500]
        assert [row.request_duration_ms for row in rows] == [1800, 1300]

    summary = next(row for row in summarize_token_usage() if row["model"] == model)
    assert summary["average_time_to_first_token_ms"] == 500.0
    assert summary["average_output_tokens_per_second"] == 12.9
    assert summary["latest_time_to_first_token_ms"] == 750
    assert summary["latest_output_tokens_per_second"] == 7.69


def test_stream_measures_first_token_and_generation_duration(monkeypatch):
    import services.llm.llm_service as llm_service
    from models.llm_token_usage import LlmTokenUsage

    model = settings.available_models[0]
    ticks = iter([10.0, 10.25, 12.25])
    monkeypatch.setattr(llm_service, "_monotonic", lambda: next(ticks))
    llm = OpenAILLMClient(_cfg(model))
    fake_client = _FakeAsyncClient([
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        'data: {"choices":[],"usage":{"completion_tokens":3,"prompt_tokens":13}}',
        "data: [DONE]",
    ])

    async def _run():
        return [
            event
            async for event in llm.stream_chat(
                [{"role": "user", "content": "hi"}],
                client=fake_client,
            )
        ]

    asyncio.run(_run())
    with database.SessionLocal() as db:
        row = db.query(LlmTokenUsage).filter_by(model_name=model).one()
        assert row.time_to_first_token_ms == 250
        assert row.generation_duration_ms == 2000
        assert row.request_duration_ms == 2250


def test_unknown_model_is_not_recorded():
    record_openai_usage("not-configured", {
        "completion_tokens": 1,
        "prompt_tokens": 2,
        "prompt_tokens_details": {"cached_tokens": 0},
    })
    assert all(row["output_tokens"] == 0 for row in summarize_token_usage())


def test_summary_lists_every_configured_model(auth_user):
    record_openai_usage(settings.available_models[2], {
        "completion_tokens": 1,
        "prompt_tokens": 9,
        "prompt_tokens_details": {"cached_tokens": 0},
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 9,
    })
    resp = client.get("/api/token-usage")
    assert resp.status_code == 200
    models = [row["model"] for row in resp.json()["models"]]
    assert models == list(settings.available_models)
    deepseek = next(row for row in resp.json()["models"] if row["model"] == settings.available_models[2])
    assert deepseek["cached_input_tokens"] == 0
    assert deepseek["uncached_input_tokens"] == 9
    assert deepseek["output_tokens"] == 1
    untouched = next(row for row in resp.json()["models"] if row["model"] == settings.available_models[0])
    assert untouched["cached_input_tokens"] == 0
    assert untouched["uncached_input_tokens"] == 0
    assert untouched["output_tokens"] == 0
    assert untouched["cached_input_percent"] is None
    assert deepseek["cached_input_percent"] == 0.0


def test_usage_filters_by_work_and_reports_cache_percent(auth_user):
    db = database.SessionLocal()
    try:
        work_a = CanvasWork(user_id=auth_user.id, title="甲作品")
        work_b = CanvasWork(user_id=auth_user.id, title="乙作品")
        db.add_all([work_a, work_b])
        db.commit()
        work_a_id, work_b_id = work_a.id, work_b.id
    finally:
        db.close()

    usage = {
        "completion_tokens": 10,
        "prompt_tokens": 18,
        "prompt_tokens_details": {"cached_tokens": 4},
    }
    token = set_context({"work_id": work_a_id})
    try:
        record_openai_usage(settings.available_models[0], usage)
    finally:
        reset_context(token)
    token = set_context({"work_id": work_b_id})
    try:
        record_openai_usage(settings.available_models[0], {
            "completion_tokens": 1,
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 10},
        })
    finally:
        reset_context(token)

    resp = client.get("/api/token-usage", params={"work_id": work_a_id})
    assert resp.status_code == 200
    body = resp.json()
    assert {item["title"] for item in body["works"]} == {"甲作品", "乙作品"}
    glm = next(row for row in body["models"] if row["model"] == settings.available_models[0])
    assert glm["cached_input_tokens"] == 4
    assert glm["uncached_input_tokens"] == 14
    assert glm["output_tokens"] == 10
    assert glm["cached_input_percent"] == 22.2
    other = next(row for row in body["models"] if row["model"] == settings.available_models[1])
    assert other["output_tokens"] == 0


def test_token_usage_rejects_another_users_work(auth_user):
    db = database.SessionLocal()
    try:
        other = User(username="other", email="other@t.t", password_hash="x")
        db.add(other)
        db.commit()
        work = CanvasWork(user_id=other.id, title="别人的作品")
        db.add(work)
        db.commit()
        work_id = work.id
    finally:
        db.close()
    resp = client.get("/api/token-usage", params={"work_id": work_id})
    assert resp.status_code == 404


def test_usage_series_splits_each_model_by_day_and_hour(auth_user):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from models.llm_token_usage import LlmTokenUsage

    shanghai = ZoneInfo("Asia/Shanghai")
    model = settings.available_models[0]
    other = settings.available_models[1]
    db = database.SessionLocal()
    try:
        db.add_all([
            LlmTokenUsage(
                model_name=model,
                cached_input_tokens=4,
                uncached_input_tokens=14,
                output_tokens=10,
                created_at=datetime(2026, 9, 23, 10, 15, tzinfo=shanghai),
            ),
            LlmTokenUsage(
                model_name=model,
                cached_input_tokens=1,
                uncached_input_tokens=1,
                output_tokens=2,
                created_at=datetime(2026, 9, 23, 10, 40, tzinfo=shanghai),
            ),
            LlmTokenUsage(
                model_name=model,
                cached_input_tokens=3,
                uncached_input_tokens=0,
                output_tokens=1,
                created_at=datetime(2026, 9, 23, 12, 5, tzinfo=shanghai),
            ),
            LlmTokenUsage(
                model_name=other,
                cached_input_tokens=8,
                uncached_input_tokens=2,
                output_tokens=3,
                created_at=datetime(2026, 9, 24, 1, 0, tzinfo=shanghai),
            ),
        ])
        db.commit()
    finally:
        db.close()

    hourly = client.get("/api/token-usage", params={"grain": "hour"})
    assert hourly.status_code == 200
    series = {row["model"]: row["points"] for row in hourly.json()["series"]}
    assert list(series) == list(settings.available_models)
    glm_hours = {point["bucket"]: point for point in series[model]}
    assert glm_hours["2026-09-23T10:00:00+08:00"]["cached_input_tokens"] == 5
    assert glm_hours["2026-09-23T10:00:00+08:00"]["uncached_input_tokens"] == 15
    assert glm_hours["2026-09-23T10:00:00+08:00"]["output_tokens"] == 12
    assert glm_hours["2026-09-23T11:00:00+08:00"]["output_tokens"] == 0
    assert glm_hours["2026-09-23T12:00:00+08:00"]["cached_input_tokens"] == 3
    assert glm_hours["2026-09-24T01:00:00+08:00"]["output_tokens"] == 0
    assert series[other][-1]["output_tokens"] == 3
    assert [point["bucket"] for point in series[model]] == [point["bucket"] for point in series[other]]

    daily = client.get("/api/token-usage", params={"grain": "day"})
    assert daily.status_code == 200
    day_series = {row["model"]: row["points"] for row in daily.json()["series"]}
    glm_days = {point["bucket"]: point for point in day_series[model]}
    assert glm_days["2026-09-23"]["cached_input_tokens"] == 8
    assert glm_days["2026-09-23"]["uncached_input_tokens"] == 15
    assert glm_days["2026-09-23"]["output_tokens"] == 13
    assert glm_days["2026-09-24"]["output_tokens"] == 0

    rejected = client.get("/api/token-usage", params={"grain": "week"})
    assert rejected.status_code == 422
