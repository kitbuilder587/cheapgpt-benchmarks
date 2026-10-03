from datetime import UTC, datetime

from cheapgpt_benchmarks.models import AttemptRecord, RequestRecord, ResponseRecord
from cheapgpt_benchmarks.scoring import extract_choice_answer, score_choice_benchmark


def attempt(item_id: str, number: int, text: str) -> AttemptRecord:
    now = datetime.now(UTC)
    return AttemptRecord(
        run_id="2026-09-03.1",
        item_id=item_id,
        benchmark="hle",
        attempt=number,
        track="default",
        requested_model="gpt-5.6-sol",
        returned_model="gpt-5.6-sol",
        started_at=now,
        finished_at=now,
        latency_ms=1,
        status="completed",
        request=RequestRecord(endpoint="/responses", headers={}, body={}),
        response=ResponseRecord(
            status_code=200,
            body={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": text}]}
                ]
            },
        ),
        content_sha256="0" * 64,
    )


def test_extract_choice_answer_supports_hle_and_mmlu_options() -> None:
    response = "Explanation: ...\nAnswer: E\nConfidence: 90%"
    assert extract_choice_answer(response, "ABCDEFGHIJ") == "E"
    assert extract_choice_answer("The correct answer is (G)", "ABCDEFGHIJ") == "G"


def test_choice_score_uses_majority_across_three_attempts() -> None:
    records = [
        attempt("hle-1", 1, "Answer: E"),
        attempt("hle-1", 2, "Answer: E"),
        attempt("hle-1", 3, "Answer: B"),
    ]

    scores, summary = score_choice_benchmark(
        records,
        {"hle-1": {"answer": "E"}},
        "hle",
        "ABCDEFGHIJ",
    )

    assert len(scores) == 3
    assert summary["score"] == 100.0
    assert summary["attempt_accuracy"] == 66.667
    assert summary["flapping_items"] == 1
