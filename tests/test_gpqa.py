import csv
import io
from datetime import UTC, datetime

from cheapgpt_benchmarks.adapters import gpqa
from cheapgpt_benchmarks.models import AttemptRecord, RequestRecord, ResponseRecord
from cheapgpt_benchmarks.scoring import extract_gpqa_answer, score_gpqa


def dataset() -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Question",
            "Correct Answer",
            "Incorrect Answer 1",
            "Incorrect Answer 2",
            "Incorrect Answer 3",
            "Record ID",
        ],
    )
    writer.writeheader()
    for index in range(198):
        writer.writerow(
            {
                "Question": f"Question {index}",
                "Correct Answer": "correct",
                "Incorrect Answer 1": "wrong 1",
                "Incorrect Answer 2": "wrong 2",
                "Incorrect Answer 3": "wrong 3",
                "Record ID": f"record-{index}",
            }
        )
    return output.getvalue().encode()


def attempt(item_id: str, text: str) -> AttemptRecord:
    now = datetime.now(UTC)
    return AttemptRecord(
        run_id="2026-09-03.1",
        item_id=item_id,
        benchmark="gpqa-diamond",
        attempt=1,
        track="leaderboard",
        requested_model="gpt-5.6-sol",
        started_at=now,
        finished_at=now,
        latency_ms=1,
        status="completed",
        request=RequestRecord(endpoint="https://example.test", headers={}, body={}),
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


def test_gpqa_adapter_builds_five_deterministic_repeats(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gpqa, "_dataset", lambda _: dataset())
    contract = gpqa.prepare_gpqa(cache_root=tmp_path)

    assert len(contract.plan) == len(contract.expected) == 990
    assert len({item.id for item in contract.plan}) == 990
    assert contract.plan[0].parameters == {
        "max_output_tokens": 128000,
        "store": False,
        "temperature": 0.6,
    }
    assert contract.plan[0].prompt.endswith("D) wrong 2")
    assert contract.expected[contract.plan[0].id] == "C"


def test_gpqa_scoring_matches_published_extraction_contract() -> None:
    assert extract_gpqa_answer("reasoning\n**Answer**: C") == "C"
    assert extract_gpqa_answer("reasoning\n\\boxed{The answer is B}") == "B"

    records = [attempt("item-1", "Answer: A"), attempt("item-2", "Answer: C")]
    scores, summary = score_gpqa(records, {"item-1": "A", "item-2": "B"})

    assert [item["score"] for item in scores] == [1, 0]
    assert summary["score"] == 50.0
    assert summary["scored_attempts"] == 2
