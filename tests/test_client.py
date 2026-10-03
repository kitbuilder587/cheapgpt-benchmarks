import asyncio

import httpx
import pytest
import respx

from cheapgpt_benchmarks.client import BenchmarkRequest, RequestRateLimiter, ResponsesClient


@respx.mock
def test_retry_records_every_attempt_and_redacts_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(_: float) -> None:
        pass

    monkeypatch.setattr("cheapgpt_benchmarks.client.asyncio.sleep", no_wait)
    route = respx.post("https://example.test/v1/responses").mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            httpx.Response(
                200,
                headers={"x-request-id": "req_123", "x-route-id": "42"},
                json={
                    "id": "resp_123",
                    "model": "gpt-5.5-2026-08-07",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "B"}],
                        }
                    ],
                    "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
                },
            ),
        ]
    )
    client = ResponsesClient("top-secret", "https://example.test/v1", 1)
    request = BenchmarkRequest(
        run_id="2026-09-02.1",
        item_id="gpqa-1",
        benchmark="gpqa-diamond",
        attempt=1,
        track="default",
        model="gpt-5.5",
        prompt="Question",
        parameters={},
    )

    records = asyncio.run(client.execute(request))
    asyncio.run(client.close())

    assert route.call_count == 2
    assert [record.status for record in records] == ["error", "completed"]
    assert records[0].retryable is True
    assert records[1].returned_model == "gpt-5.5-2026-08-07"
    assert records[1].request.headers["Authorization"] == "[REDACTED]"
    assert records[1].response.headers == {"content-type": "application/json"}
    assert records[1].request_id is None
    assert "top-secret" not in records[1].model_dump_json()


@respx.mock
def test_request_errors_are_recorded_and_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(_: float) -> None:
        pass

    monkeypatch.setattr("cheapgpt_benchmarks.client.asyncio.sleep", no_wait)
    route = respx.post("https://example.test/v1/responses").mock(
        side_effect=[
            httpx.LocalProtocolError("invalid header"),
            httpx.Response(200, json={"model": "gpt-5.6-sol"}),
        ]
    )
    client = ResponsesClient("secret", "https://example.test/v1", 1)
    request = BenchmarkRequest(
        run_id="2026-09-02.1",
        item_id="mmlu-pro-1",
        benchmark="mmlu-pro",
        attempt=1,
        track="default",
        model="gpt-5.6-sol",
        prompt="Question",
        parameters={},
    )

    records = asyncio.run(client.execute(request))
    asyncio.run(client.close())

    assert route.call_count == 2
    assert [record.status for record in records] == ["error", "completed"]
    assert records[0].error == {
        "type": "LocalProtocolError",
        "message": "invalid header",
        "transport_attempt": 1,
    }
    assert records[0].retryable is True


@respx.mock
def test_streaming_response_preserves_terminal_response() -> None:
    route = respx.post("https://example.test/v1/responses").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-request-id": "req_stream"},
            text=(
                'event: response.created\n'
                'data: {"type":"response.created","response":{"status":"in_progress"}}\n\n'
                'event: response.output_text.delta\n'
                'data: {"type":"response.output_text.delta","delta":"B"}\n\n'
                'event: response.completed\n'
                'data: {"type":"response.completed","response":{"id":"resp_stream",'
                '"model":"gpt-5.6-sol","output":[{"type":"message","content":'
                '[{"type":"output_text","text":"B"}]}],"usage":{"input_tokens":12,'
                '"output_tokens":3,"total_tokens":15}}}\n\n'
            ),
        )
    )
    client = ResponsesClient("secret", "https://example.test/v1", 1)
    request = BenchmarkRequest(
        run_id="2026-09-02.1",
        item_id="arc-1",
        benchmark="arc-agi-2",
        attempt=1,
        track="leaderboard",
        model="gpt-5.6-sol",
        prompt="Question",
        parameters={},
    )

    records = asyncio.run(client.execute(request))
    asyncio.run(client.close())

    assert route.call_count == 1
    assert route.calls[0].request.content is not None
    assert b'"stream":true' in route.calls[0].request.content
    assert records[0].status == "completed"
    assert records[0].returned_model == "gpt-5.6-sol"
    assert records[0].response.body is not None
    assert records[0].response.body["id"] == "resp_stream"
    assert records[0].usage is not None
    assert records[0].usage.total_tokens == 15


def test_rate_limiter_caps_a_rolling_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 0.0

    def monotonic() -> float:
        return clock

    async def sleep(delay: float) -> None:
        nonlocal clock
        clock += delay

    monkeypatch.setattr("cheapgpt_benchmarks.client.time.monotonic", monotonic)
    monkeypatch.setattr("cheapgpt_benchmarks.client.asyncio.sleep", sleep)
    limiter = RequestRateLimiter(2)

    async def exercise() -> list[float]:
        timestamps = []
        for _ in range(3):
            await limiter.acquire()
            timestamps.append(clock)
        return timestamps

    assert asyncio.run(exercise()) == [0.0, 0.0, 60.0]
