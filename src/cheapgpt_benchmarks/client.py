import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from cheapgpt_benchmarks.constants import RETRYABLE_STATUS_CODES
from cheapgpt_benchmarks.hashing import content_sha256
from cheapgpt_benchmarks.models import (
    AttemptRecord,
    RequestRecord,
    ResponseRecord,
    UsageRecord,
)
from cheapgpt_benchmarks.sanitize import sanitize


@dataclass(frozen=True)
class BenchmarkRequest:
    run_id: str
    item_id: str
    benchmark: str
    attempt: int
    track: Literal["default", "leaderboard"]
    model: str
    prompt: str
    parameters: dict[str, Any]


class RequestRateLimiter:
    def __init__(self, requests_per_minute: int | None) -> None:
        self._limit = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._limit is None:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - 60
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                delay = self._timestamps[0] + 60 - now
            await asyncio.sleep(max(delay, 0.001))


class ResponsesClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float,
        max_rpm: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/responses"
        self._client = httpx.AsyncClient(timeout=timeout)
        self._rate_limiter = RequestRateLimiter(max_rpm)

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, request: BenchmarkRequest) -> list[AttemptRecord]:
        records: list[AttemptRecord] = []
        for retry_index in range(3):
            record = await self._execute_once(request, retry_index + 1)
            records.append(record)
            if record.status == "completed" or not record.retryable:
                break
            if retry_index < 2:
                await asyncio.sleep((10, 30)[retry_index])
        return records

    async def _execute_once(
        self, request: BenchmarkRequest, transport_attempt: int
    ) -> AttemptRecord:
        await self._rate_limiter.acquire()
        body = {
            "model": request.model,
            "input": request.prompt,
            **request.parameters,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        response_record = ResponseRecord()
        returned_model = None
        usage = None
        error = None
        retryable = False
        status: Literal["completed", "error"] = "error"

        try:
            async with self._client.stream(
                "POST", self._endpoint, headers=headers, json=body
            ) as response:
                response_headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower()
                    in {"content-type", "openai-processing-ms"}
                }
                response_body, raw_text = await _read_response(response)
                response_record = ResponseRecord(
                    status_code=response.status_code,
                    headers=sanitize(response_headers),
                    body=sanitize(response_body) if isinstance(response_body, dict) else None,
                    raw_text=None if isinstance(response_body, dict) else sanitize(raw_text),
                )
                retryable = response.status_code in RETRYABLE_STATUS_CODES or (
                    response.is_success and response_body is None
                )
                if response.is_success and isinstance(response_body, dict):
                    status = "completed"
                    returned_model = response_body.get("model")
                    raw_usage = response_body.get("usage")
                    if isinstance(raw_usage, dict):
                        usage = UsageRecord(
                            input_tokens=raw_usage.get("input_tokens"),
                            output_tokens=raw_usage.get("output_tokens"),
                            total_tokens=raw_usage.get("total_tokens"),
                            details=sanitize(raw_usage),
                        )
                else:
                    error = {
                        "type": "stream_error" if response.is_success else "http_error",
                        "transport_attempt": transport_attempt,
                    }
        except httpx.RequestError as exc:
            retryable = True
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "transport_attempt": transport_attempt,
            }

        finished_at = datetime.now(UTC)
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        safe_request = RequestRecord(
            endpoint=self._endpoint,
            headers=sanitize(headers),
            body=sanitize(body),
        )
        hash_payload = {
            "request": safe_request.model_dump(mode="json"),
            "response": response_record.model_dump(mode="json"),
            "error": error,
        }
        return AttemptRecord(
            run_id=request.run_id,
            item_id=request.item_id,
            benchmark=request.benchmark,
            attempt=request.attempt,
            track=request.track,
            requested_model=request.model,
            returned_model=returned_model,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
            status=status,
            request=safe_request,
            response=response_record,
            usage=usage,
            error=error,
            retryable=retryable,
            content_sha256=content_sha256(hash_payload),
        )


async def _read_response(response: httpx.Response) -> tuple[dict[str, Any] | None, str]:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" not in content_type:
        raw = (await response.aread()).decode(response.encoding or "utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None, raw
        return (parsed if isinstance(parsed, dict) else None), raw

    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line or not data_lines:
            continue
        payload = _parse_sse_data(data_lines)
        data_lines = []
        if payload is not None:
            return payload, ""
    if data_lines:
        payload = _parse_sse_data(data_lines)
        if payload is not None:
            return payload, ""
    return None, "stream ended without a terminal response event"


def _parse_sse_data(data_lines: list[str]) -> dict[str, Any] | None:
    try:
        event = json.loads("\n".join(data_lines))
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("type") not in {
        "response.completed",
        "response.failed",
        "response.incomplete",
    }:
        return None
    response = event.get("response")
    return response if isinstance(response, dict) else None
