import asyncio
import io
import json
import tarfile
from datetime import UTC, datetime

import httpx
import respx

from cheapgpt_benchmarks.adapters import arc_agi_2
from cheapgpt_benchmarks.models import AttemptRecord, RequestRecord, ResponseRecord
from cheapgpt_benchmarks.plan import PlanItem
from cheapgpt_benchmarks.runner import run_plan
from cheapgpt_benchmarks.scoring import extract_arc_grid, score_arc_agi_2
from cheapgpt_benchmarks.verify import verify_run


def dataset() -> bytes:
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
        for index in range(120):
            task_id = f"{index:08x}"
            test_count = 2 if index < 47 else 1
            task = {
                "train": [{"input": [[1]], "output": [[2]]}],
                "test": [
                    {"input": [[3 + pair]], "output": [[4 + pair]]} for pair in range(test_count)
                ],
            }
            payload = json.dumps(task).encode()
            info = tarfile.TarInfo(f"ARC-AGI-2/data/evaluation/{task_id}.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return archive_bytes.getvalue()


def attempt(item_id: str, number: int, text: str) -> AttemptRecord:
    now = datetime.now(UTC)
    return AttemptRecord(
        run_id="2026-09-04.1",
        item_id=item_id,
        benchmark="arc-agi-2",
        attempt=number,
        track="leaderboard",
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
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]
            },
        ),
        content_sha256="0" * 64,
    )


def test_adapter_builds_official_public_eval_contract(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(arc_agi_2, "_dataset", lambda _: dataset())
    contract = arc_agi_2.prepare_arc_agi_2(tmp_path)

    assert len(contract.plan) == len(contract.expected) == 167
    assert sum(item.attempts or 0 for item in contract.plan) == 334
    assert contract.plan[0].parameters == {"max_output_tokens": 128000, "store": False}
    assert contract.plan[0].prompt == arc_agi_2.PROMPT.format(
        training_examples="--Example 0-- \n\n INPUT: \n\n[[1]]\n\nOUTPUT: \n\n[[2]]\n\n",
        test_input="[[3]]",
    )


def test_scoring_accepts_either_attempt_and_averages_by_task() -> None:
    expected = {
        "arc-agi-2-a-p1": {"task_id": "a", "pair_index": 0, "answer": [[1]]},
        "arc-agi-2-b-p1": {"task_id": "b", "pair_index": 0, "answer": [[2]]},
        "arc-agi-2-b-p2": {"task_id": "b", "pair_index": 1, "answer": [[3]]},
    }
    records = [
        attempt("arc-agi-2-a-p1", 1, "wrong [[0]]"),
        attempt("arc-agi-2-a-p1", 2, "final [[1]]"),
        attempt("arc-agi-2-b-p1", 1, "[[2]]"),
        attempt("arc-agi-2-b-p2", 1, "[[0]]"),
    ]

    scores, summary = score_arc_agi_2(records, expected)

    assert extract_arc_grid("analysis [0]\n```json\n[[1, 2], [3, 4]]\n```") == [[1, 2], [3, 4]]
    assert extract_arc_grid('answer \\boxed{[[1, "2"]]} trailing }') == [[1, 2]]
    assert [item["score"] for item in scores] == [0, 1, 1, 0]
    assert summary["task_scores"] == {"a": 1.0, "b": 0.5}
    assert summary["score"] == 75.0


@respx.mock
def test_arc_run_writes_deterministically_verifiable_scores(tmp_path) -> None:
    respx.post("https://example.test/v1/responses").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "[[[0]]]"}],
                        }
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "[[1]]"}],
                        }
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "[[0]]"}],
                        }
                    ],
                },
            ),
        ]
    )
    lock = tmp_path / "benchmarks.lock.yaml"
    lock.write_text("schema_version: 1\n")
    item_id = "arc-agi-2-a-p1"
    _, run_root = asyncio.run(
        run_plan(
            api_key="secret",
            base_url="https://example.test/v1",
            timeout=1,
            model="gpt-5.6-sol",
            profile="full-v1",
            track="leaderboard",
            attempts_per_item=1,
            plan=[
                PlanItem(
                    id=item_id,
                    benchmark="arc-agi-2",
                    prompt="Puzzle",
                    attempts=2,
                )
            ],
            output_root=tmp_path / "runs",
            benchmark_lock=lock,
            concurrency=1,
            arc_scoring_key={item_id: {"task_id": "a", "pair_index": 0, "answer": [[1]]}},
        )
    )

    assert json.loads((run_root / "score-summary.json").read_text())["score"] == 100.0
    assert verify_run(run_root) == {"attempt_count": 3, "logical_attempt_count": 2}
