from datetime import UTC, datetime
from pathlib import Path

import pytest

from cheapgpt_benchmarks.hashing import content_sha256
from cheapgpt_benchmarks.models import AttemptRecord, RequestRecord, ResponseRecord, RunManifest
from cheapgpt_benchmarks.sanitize import sanitize
from cheapgpt_benchmarks.verify import verify_run


def test_sanitize_nested_secrets_and_bearer_tokens() -> None:
    value = {
        "Authorization": "Bearer secret-token",
        "nested": {"api_key": "secret", "message": "use Bearer another.secret"},
        "safe": ["visible"],
    }

    assert sanitize(value) == {
        "Authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "message": "use Bearer [REDACTED]"},
        "safe": ["visible"],
    }


def test_sanitize_removes_provider_linkable_identifiers() -> None:
    value = {
        "id": "resp_0123456789abcdef0123456789abcdef0123456789abcdef",
        "safety_identifier": "user-ExampleExampleExample0",
        "prompt_cache_key": "00000000-0000-7000-8000-000000000001",
        "user": None,
        "output": [
            {
                "id": "rs_fedcba9876543210fedcba9876543210fedcba9876543210",
                "encrypted_content": "encrypted-example",
                "metadata": {"turn_id": "00000000-0000-7000-8000-000000000002"},
                "internal_metadata": {"turn_id": "x"},
            }
        ],
        "usage": {"input_tokens": 1, "attribution": {"items": {}}},
        "raw_text": "stream timeout\nrequest-id: 00000000-0000-4000-8000-000000000003\n",
    }

    sanitized = sanitize(value)

    assert sanitized == {
        "id": "resp_[REDACTED]",
        "safety_identifier": "[REDACTED]",
        "prompt_cache_key": "[REDACTED]",
        "user": None,
        "output": [
            {
                "id": "rs_[REDACTED]",
                "encrypted_content": "[REDACTED]",
                "metadata": {"turn_id": "[REDACTED]"},
            }
        ],
        "usage": {"input_tokens": 1},
        "raw_text": "stream timeout\nrequest-id: [REDACTED]\n",
    }
    assert sanitize(sanitized) == sanitized


def test_verify_run_rejects_unredacted_sensitive_values(tmp_path: Path) -> None:
    request = RequestRecord(
        endpoint="https://example.test/v1/responses",
        headers={"Authorization": "Bearer leaked-token"},
        body={"model": "gpt-5.6-sol", "input": "fixture"},
    )
    response = ResponseRecord(status_code=200, body={"model": "gpt-5.6-sol"})
    payload = {
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
        "error": None,
    }
    record = AttemptRecord(
        run_id="2026-09-03.1",
        item_id="fixture",
        benchmark="gpqa-diamond",
        attempt=1,
        track="leaderboard",
        requested_model="gpt-5.6-sol",
        returned_model="gpt-5.6-sol",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        latency_ms=1,
        status="completed",
        request=request,
        response=response,
        content_sha256=content_sha256(payload),
    )
    manifest = RunManifest(
        run_id=record.run_id,
        cli_version="0.1.0",
        profile="full-v1",
        track="leaderboard",
        model=record.requested_model,
        started_at=record.started_at,
        finished_at=record.finished_at,
        status="completed",
        benchmark_lock_sha256="0" * 64,
        attempt_count=1,
        completed_count=1,
        error_count=0,
        expected_logical_attempt_count=1,
        completed_logical_attempt_count=1,
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (tmp_path / "attempts.jsonl").write_text(record.model_dump_json() + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sensitive value"):
        verify_run(tmp_path)
