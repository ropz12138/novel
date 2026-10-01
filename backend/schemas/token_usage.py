from pydantic import BaseModel


class TokenUsageWork(BaseModel):
    id: str
    title: str


class TokenUsageItem(BaseModel):
    model: str
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    cached_input_percent: float | None
    average_time_to_first_token_ms: float | None
    average_output_tokens_per_second: float | None
    latest_time_to_first_token_ms: int | None
    latest_output_tokens_per_second: float | None


class TokenUsagePoint(BaseModel):
    bucket: str
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int


class TokenUsageSeries(BaseModel):
    model: str
    points: list[TokenUsagePoint]


class TokenUsageResponse(BaseModel):
    works: list[TokenUsageWork]
    models: list[TokenUsageItem]
    series: list[TokenUsageSeries]
