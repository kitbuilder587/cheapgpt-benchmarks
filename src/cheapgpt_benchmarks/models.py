from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequestRecord(StrictModel):
    endpoint: str
    headers: dict[str, str]
    body: dict[str, Any]


class ResponseRecord(StrictModel):
    status_code: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    raw_text: str | None = None


class UsageRecord(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AttemptRecord(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    item_id: str
    benchmark: str
    attempt: int = Field(ge=1)
    track: Literal["default", "leaderboard"]
    requested_model: str
    returned_model: str | None = None
    request_id: str | None = None
    started_at: datetime
    finished_at: datetime
    latency_ms: int = Field(ge=0)
    status: Literal["completed", "error"]
    request: RequestRecord
    response: ResponseRecord
    usage: UsageRecord | None = None
    error: dict[str, Any] | None = None
    retryable: bool = False
    content_sha256: str

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(UTC)


class RunManifest(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    cli_version: str
    profile: str
    track: Literal["default", "leaderboard"]
    model: str
    reasoning_effort: str | None = None
    benchmark_contract: str | None = None
    dataset_sha256: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "completed", "incomplete"]
    benchmark_lock_sha256: str
    attempt_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    expected_logical_attempt_count: int = Field(default=0, ge=0)
    completed_logical_attempt_count: int = Field(default=0, ge=0)
