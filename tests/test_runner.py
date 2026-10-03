import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from cheapgpt_benchmarks.client import BenchmarkRequest, ResponsesClient
from cheapgpt_benchmarks.models import AttemptRecord
from cheapgpt_benchmarks.plan import PlanItem
from cheapgpt_benchmarks.runner import next_run_id, run_plan
from cheapgpt_benchmarks.verify import verify_run


def test_next_run_id_increments_existing_run(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    (tmp_path / "2026-09-02.1").mkdir()

    assert next_run_id(tmp_path, now) == "2026-09-02.2"


@respx.mock
def test_run_writes_verifiable_artifacts(tmp_path: Path) -> None:
    respx.post("https://example.test/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_1",
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "one\u2028two"}],
                    }
                ],
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            },
        )
    )
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")

    manifest, run_root = asyncio.run(
        run_plan(
            api_key="secret",
            base_url="https://example.test/v1",
            timeout=1,
            model="gpt-5.5",
            profile="quick-v1",
            track="default",
            attempts_per_item=1,
            plan=[PlanItem(id="hle-1", benchmark="hle", prompt="Question")],
            output_root=tmp_path / "runs",
            benchmark_lock=lock,
            concurrency=1,
        )
    )

    assert manifest.status == "completed"
    assert (run_root / "report.html").exists()
    attempt = json.loads((run_root / "attempts.jsonl").read_text())
    assert attempt["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert verify_run(run_root) == {"attempt_count": 1, "logical_attempt_count": 1}


def test_unhandled_client_failure_marks_run_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(ResponsesClient, "execute", fail)
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")
    output_root = tmp_path / "runs"

    with pytest.raises(RuntimeError, match="unexpected failure"):
        asyncio.run(
            run_plan(
                api_key="secret",
                base_url="https://example.test/v1",
                timeout=1,
                model="gpt-5.6-sol",
                profile="quick-v1",
                track="default",
                attempts_per_item=1,
                plan=[PlanItem(id="mmlu-1", benchmark="mmlu-pro", prompt="Question")],
                output_root=output_root,
                benchmark_lock=lock,
                concurrency=1,
            )
        )

    manifest = json.loads(next(output_root.iterdir()).joinpath("manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert manifest["finished_at"] is not None


@respx.mock
def test_cost_stop_marks_run_incomplete_after_persisting_attempt(tmp_path: Path) -> None:
    route = respx.post("https://example.test/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "openai/gpt-5.6-sol",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "cost": 0.25,
                },
            },
        )
    )
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")
    output_root = tmp_path / "runs"

    with pytest.raises(RuntimeError, match=r"\$0.2500 reached the \$0.20 stop"):
        asyncio.run(
            run_plan(
                api_key="secret",
                base_url="https://example.test/v1",
                timeout=1,
                model="openai/gpt-5.6-sol",
                profile="full-v1",
                track="leaderboard",
                attempts_per_item=1,
                plan=[
                    PlanItem(id="gpqa-1", benchmark="gpqa-diamond", prompt="Question 1"),
                    PlanItem(id="gpqa-2", benchmark="gpqa-diamond", prompt="Question 2"),
                ],
                output_root=output_root,
                benchmark_lock=lock,
                concurrency=1,
                max_cost_usd=0.20,
            )
        )

    run_root = next(output_root.iterdir())
    manifest = json.loads((run_root / "manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert manifest["attempt_count"] == 1
    assert manifest["completed_count"] == 1
    assert len((run_root / "attempts.jsonl").read_text().splitlines()) == 1
    assert route.call_count == 1


@respx.mock
def test_returned_model_mismatch_aborts_before_full_run(tmp_path: Path) -> None:
    route = respx.post("https://example.test/v1/responses").mock(
        return_value=httpx.Response(200, json={"model": "gpt-5.6-luna"})
    )
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")

    with pytest.raises(RuntimeError, match="does not match"):
        asyncio.run(
            run_plan(
                api_key="secret",
                base_url="https://example.test/v1",
                timeout=1,
                model="gpt-5.6-sol",
                profile="full-v1",
                track="leaderboard",
                attempts_per_item=1,
                plan=[
                    PlanItem(id="gpqa-1", benchmark="gpqa-diamond", prompt="Question 1"),
                    PlanItem(id="gpqa-2", benchmark="gpqa-diamond", prompt="Question 2"),
                ],
                output_root=tmp_path / "runs",
                benchmark_lock=lock,
                concurrency=4,
            )
        )

    assert route.call_count == 1


@respx.mock
def test_completed_attempts_are_persisted_before_later_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_execute = ResponsesClient.execute
    completed = asyncio.Event()

    async def complete_then_fail(
        self: ResponsesClient, request: BenchmarkRequest
    ) -> list[AttemptRecord]:
        if request.item_id == "mmlu-1":
            result = await original_execute(self, request)
            completed.set()
            return result
        await completed.wait()
        raise RuntimeError("later failure")

    respx.post("https://example.test/v1/responses").mock(
        return_value=httpx.Response(200, json={"model": "gpt-5.6-sol"})
    )
    monkeypatch.setattr(ResponsesClient, "execute", complete_then_fail)
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")
    output_root = tmp_path / "runs"

    with pytest.raises(RuntimeError, match="later failure"):
        asyncio.run(
            run_plan(
                api_key="secret",
                base_url="https://example.test/v1",
                timeout=1,
                model="gpt-5.6-sol",
                profile="full-v1",
                track="default",
                attempts_per_item=1,
                plan=[
                    PlanItem(id="mmlu-1", benchmark="mmlu-pro", prompt="Question"),
                    PlanItem(id="mmlu-2", benchmark="mmlu-pro", prompt="Question"),
                ],
                output_root=output_root,
                benchmark_lock=lock,
                concurrency=2,
            )
        )

    run_root = next(output_root.iterdir())
    manifest = json.loads((run_root / "manifest.json").read_text())
    attempts = (run_root / "attempts.jsonl").read_text().splitlines()
    assert manifest["completed_count"] == 1
    assert len(attempts) == 1


@respx.mock
def test_resume_only_retries_incomplete_logical_attempts(tmp_path: Path) -> None:
    route = respx.post("https://example.test/v1/responses").mock(
        side_effect=[
            httpx.Response(200, json={"model": "gpt-5.6-sol"}),
            httpx.Response(400, json={"error": {"message": "bad"}}),
        ]
    )
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")
    output_root = tmp_path / "runs"
    plan = [
        PlanItem(id="gpqa-1", benchmark="gpqa-diamond", prompt="Question 1"),
        PlanItem(id="gpqa-2", benchmark="gpqa-diamond", prompt="Question 2"),
    ]

    with pytest.raises(RuntimeError, match="Non-retryable API error"):
        asyncio.run(
            run_plan(
                api_key="secret",
                base_url="https://example.test/v1",
                timeout=1,
                model="gpt-5.6-sol",
                profile="full-v1",
                track="leaderboard",
                attempts_per_item=1,
                plan=plan,
                output_root=output_root,
                benchmark_lock=lock,
                concurrency=1,
                reasoning_effort="low",
            )
        )
    run_root = next(output_root.iterdir())
    assert json.loads((run_root / "manifest.json").read_text())["status"] == "incomplete"

    route.side_effect = None
    route.return_value = httpx.Response(200, json={"model": "gpt-5.6-sol"})
    resumed_manifest, resumed_root = asyncio.run(
        run_plan(
            api_key="secret",
            base_url="https://example.test/v1",
            timeout=1,
            model="gpt-5.6-sol",
            profile="full-v1",
            track="leaderboard",
            attempts_per_item=1,
            plan=plan,
            output_root=output_root,
            benchmark_lock=lock,
            concurrency=1,
            reasoning_effort="low",
            resume_root=run_root,
        )
    )

    assert resumed_root == run_root
    assert resumed_manifest.status == "completed"
    assert resumed_manifest.attempt_count == 3
    assert route.call_count == 3
