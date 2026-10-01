"""把 OpenAI 兼容 usage 拆成缓存输入、未缓存输入、输出，并按模型累计。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, text

from config import settings
from models.llm_token_usage import LlmTokenUsage

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _as_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_openai_token_usage(usage: dict | None) -> tuple[int, int, int] | None:
    """返回 (cached_input, uncached_input, output)。

    供应商未返回缓存明细时，prompt_tokens 全部记为未缓存输入。
    """
    if not isinstance(usage, dict):
        return None
    output = _as_int(usage.get("completion_tokens"))
    prompt = _as_int(usage.get("prompt_tokens"))
    if output is None or prompt is None or output < 0 or prompt < 0:
        return None
    hit = _as_int(usage.get("prompt_cache_hit_tokens"))
    miss = _as_int(usage.get("prompt_cache_miss_tokens"))
    if hit is not None and miss is not None:
        cached, uncached = hit, miss
    else:
        details = usage.get("prompt_tokens_details")
        cached = _as_int(details.get("cached_tokens")) if isinstance(details, dict) else None
        if cached is None:
            cached, uncached = 0, prompt
        else:
            uncached = prompt - cached
    if cached < 0 or uncached < 0:
        return None
    return cached, uncached, output


def cached_input_percent(cached: int, uncached: int) -> float | None:
    total = cached + uncached
    if total == 0:
        return None
    return round(cached * 100 / total, 1)


def current_work_id() -> str | None:
    from services.agents.supervisor import get_context
    work_id = get_context().get("work_id")
    if not work_id:
        return None
    return str(work_id)


def ensure_llm_token_usage_work_column() -> None:
    from database import engine
    with engine.begin() as conn:
        table = conn.execute(text("SELECT to_regclass('public.llm_token_usage')")).scalar()
        if table is None:
            return
        columns = {
            row[0]
            for row in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'llm_token_usage'"
            ))
        }
        if "work_id" not in columns:
            conn.execute(text("ALTER TABLE llm_token_usage ADD COLUMN work_id VARCHAR(36)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_llm_token_usage_work_id ON llm_token_usage (work_id)"))
        for name in (
            "time_to_first_token_ms",
            "generation_duration_ms",
            "request_duration_ms",
        ):
            if name not in columns:
                conn.execute(text(
                    f"ALTER TABLE llm_token_usage ADD COLUMN {name} BIGINT"
                ))


def record_openai_usage(
    model_name: str,
    usage: dict | None,
    *,
    time_to_first_token_ms: int | None = None,
    generation_duration_ms: int | None = None,
    request_duration_ms: int | None = None,
) -> None:
    if model_name not in settings.available_models:
        return
    parsed = parse_openai_token_usage(usage)
    if parsed is None:
        return
    cached, uncached, output = parsed
    from database import SessionLocal
    db = SessionLocal()
    try:
        db.add(LlmTokenUsage(
            model_name=model_name,
            work_id=current_work_id(),
            cached_input_tokens=cached,
            uncached_input_tokens=uncached,
            output_tokens=output,
            time_to_first_token_ms=time_to_first_token_ms,
            generation_duration_ms=generation_duration_ms,
            request_duration_ms=request_duration_ms,
        ))
        db.commit()
    finally:
        db.close()


def summarize_token_usage(work_id: str | None = None) -> list[dict]:
    from database import SessionLocal
    db = SessionLocal()
    try:
        query = db.query(
            LlmTokenUsage.model_name,
            func.sum(LlmTokenUsage.cached_input_tokens),
            func.sum(LlmTokenUsage.uncached_input_tokens),
            func.sum(LlmTokenUsage.output_tokens),
        )
        if work_id:
            query = query.filter(LlmTokenUsage.work_id == work_id)
        rows = query.group_by(LlmTokenUsage.model_name).all()
        timing_query = db.query(LlmTokenUsage)
        if work_id:
            timing_query = timing_query.filter(LlmTokenUsage.work_id == work_id)
        timing_rows = timing_query.order_by(
            LlmTokenUsage.created_at.desc(),
            LlmTokenUsage.id.desc(),
        ).all()
    finally:
        db.close()
    totals = {
        model_name: (int(cached or 0), int(uncached or 0), int(output or 0))
        for model_name, cached, uncached, output in rows
    }
    timing_totals: dict[str, dict[str, int | list[int]]] = {}
    latest: dict[str, LlmTokenUsage] = {}
    for row in timing_rows:
        latest.setdefault(row.model_name, row)
        values = timing_totals.setdefault(row.model_name, {
            "output_tokens": 0,
            "request_duration_ms": 0,
            "first_token_values": [],
        })
        if row.request_duration_ms is not None and row.request_duration_ms > 0:
            values["output_tokens"] += int(row.output_tokens)
            values["request_duration_ms"] += int(row.request_duration_ms)
        if row.time_to_first_token_ms is not None:
            values["first_token_values"].append(int(row.time_to_first_token_ms))

    def speed(output_tokens: int, duration_ms: int | None) -> float | None:
        if duration_ms is None or duration_ms <= 0:
            return None
        return round(output_tokens * 1000 / duration_ms, 2)

    summarized = []
    for name in settings.available_models:
        cached, uncached, output = totals.get(name, (0, 0, 0))
        timing = timing_totals.get(name, {})
        first_token_values = timing.get("first_token_values", [])
        average_first_token = (
            round(sum(first_token_values) / len(first_token_values), 1)
            if first_token_values else None
        )
        latest_row = latest.get(name)
        summarized.append({
            "model": name,
            "cached_input_tokens": cached,
            "uncached_input_tokens": uncached,
            "output_tokens": output,
            "cached_input_percent": cached_input_percent(cached, uncached),
            "average_time_to_first_token_ms": average_first_token,
            "average_output_tokens_per_second": speed(
                int(timing.get("output_tokens", 0)),
                int(timing.get("request_duration_ms", 0)),
            ),
            "latest_time_to_first_token_ms": (
                latest_row.time_to_first_token_ms if latest_row else None
            ),
            "latest_output_tokens_per_second": (
                speed(latest_row.output_tokens, latest_row.request_duration_ms)
                if latest_row else None
            ),
        })
    return summarized


def _bucket_start(moment: datetime, grain: str) -> datetime:
    if grain not in {"day", "hour"}:
        raise ValueError(f"未知时间粒度：{grain}")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(SHANGHAI)
    if grain == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _format_bucket(start: datetime, grain: str) -> str:
    if grain == "hour":
        return start.strftime("%Y-%m-%dT%H:00:00+08:00")
    return start.strftime("%Y-%m-%d")


def _next_bucket(start: datetime, grain: str) -> datetime:
    if grain == "hour":
        return start + timedelta(hours=1)
    return start + timedelta(days=1)


def series_token_usage(work_id: str | None, grain: str) -> list[dict]:
    from database import SessionLocal
    db = SessionLocal()
    try:
        query = db.query(LlmTokenUsage)
        if work_id:
            query = query.filter(LlmTokenUsage.work_id == work_id)
        rows = query.all()
    finally:
        db.close()

    totals: dict[str, dict[datetime, list[int]]] = {}
    for row in rows:
        if row.model_name not in settings.available_models:
            continue
        start = _bucket_start(row.created_at, grain)
        bucket = totals.setdefault(row.model_name, {}).setdefault(start, [0, 0, 0])
        bucket[0] += int(row.cached_input_tokens)
        bucket[1] += int(row.uncached_input_tokens)
        bucket[2] += int(row.output_tokens)

    buckets: list[datetime] = []
    if totals:
        cursor = min(min(model_totals) for model_totals in totals.values())
        last = max(max(model_totals) for model_totals in totals.values())
        while cursor <= last:
            buckets.append(cursor)
            cursor = _next_bucket(cursor, grain)

    series = []
    for name in settings.available_models:
        model_totals = totals.get(name, {})
        series.append({
            "model": name,
            "points": [
                {
                    "bucket": _format_bucket(start, grain),
                    "cached_input_tokens": model_totals.get(start, [0, 0, 0])[0],
                    "uncached_input_tokens": model_totals.get(start, [0, 0, 0])[1],
                    "output_tokens": model_totals.get(start, [0, 0, 0])[2],
                }
                for start in buckets
            ],
        })
    return series
