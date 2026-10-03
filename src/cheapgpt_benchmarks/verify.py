import json
from pathlib import Path
from typing import TypedDict

from cheapgpt_benchmarks.hashing import content_sha256
from cheapgpt_benchmarks.models import AttemptRecord, RunManifest
from cheapgpt_benchmarks.sanitize import sanitize


class VerificationResult(TypedDict):
    attempt_count: int
    logical_attempt_count: int


def verify_run(root: Path) -> VerificationResult:
    manifest = RunManifest.model_validate_json((root / "manifest.json").read_text())
    records = [
        AttemptRecord.model_validate_json(line)
        for line in (root / "attempts.jsonl").read_text().split("\n")
        if line.strip()
    ]
    if len(records) != manifest.attempt_count:
        raise ValueError(
            f"Manifest says {manifest.attempt_count} attempts, artifact contains {len(records)}"
        )
    completed_count = sum(record.status == "completed" for record in records)
    error_count = sum(record.status == "error" for record in records)
    if completed_count != manifest.completed_count or error_count != manifest.error_count:
        raise ValueError("Manifest transport counts do not match attempts")
    for record in records:
        if (
            record.run_id != manifest.run_id
            or record.track != manifest.track
            or record.requested_model != manifest.model
        ):
            raise ValueError(f"Run identity mismatch for {record.benchmark}/{record.item_id}")
        if record.status == "completed" and record.returned_model != manifest.model:
            raise ValueError(f"Returned model mismatch for {record.benchmark}/{record.item_id}")
        published_payload = {
            "request": record.request.model_dump(mode="json"),
            "response": record.response.model_dump(mode="json"),
            "error": record.error,
        }
        if sanitize(published_payload) != published_payload:
            raise ValueError(f"Sensitive value in {record.benchmark}/{record.item_id}")
        expected = content_sha256(published_payload)
        if expected != record.content_sha256:
            raise ValueError(f"Hash mismatch for {record.benchmark}/{record.item_id}")
    score_summary = root / "score-summary.json"
    if score_summary.exists():
        scoring_key = json.loads((root / "scoring-key.json").read_text(encoding="utf-8"))
        stored_scores = [
            json.loads(line)
            for line in (root / "scores.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        stored_summary = json.loads(score_summary.read_text(encoding="utf-8"))
        if stored_summary.get("benchmark") == "arc-agi-2":
            from cheapgpt_benchmarks.scoring import score_arc_agi_2

            scores, summary = score_arc_agi_2(records, scoring_key)
            complete_scores = summary["scored_attempts"] == summary["expected_attempts"]
        elif "benchmarks" in stored_summary:
            from cheapgpt_benchmarks.scoring import score_choice_benchmark

            scores = []
            summaries = {}
            alphabets = {
                "gpqa-diamond": "ABCD",
                "hle": "ABCDEFGHIJ",
                "mmlu-pro": "ABCDEFGHIJ",
            }
            for benchmark, expected_answers in scoring_key.items():
                benchmark_scores, summary = score_choice_benchmark(
                    records, expected_answers, benchmark, alphabets[benchmark]
                )
                scores.extend(benchmark_scores)
                summaries[benchmark] = summary
            external_benchmarks = {
                record.benchmark for record in records
            }.intersection({"livebench", "livecodebench"})
            if external_benchmarks:
                from cheapgpt_benchmarks.sandbox import sandbox_score_outputs

                package_root = Path(__file__).resolve().parent
                quick_root = package_root / "quick" / "expected"
                docker_root = package_root / "docker"
                if not quick_root.exists():
                    repository_root = package_root.parents[1]
                    quick_root = repository_root / "quick" / "expected"
                    docker_root = repository_root / "docker"
                external_scores, external_summaries = sandbox_score_outputs(
                    root,
                    quick_root,
                    docker_root,
                )
                scores.extend(external_scores)
                summaries.update(
                    {
                        name: value
                        for name, value in external_summaries.items()
                        if name in external_benchmarks
                    }
                )
            summary = {
                "profile": "quick-v1",
                "benchmarks": summaries,
                "scored_benchmarks": len(summaries),
                "expected_benchmarks": len({record.benchmark for record in records}),
            }
            complete_scores = all(
                item["scored_attempts"] == item["questions"] * item["attempts_per_item"]
                for item in summaries.values()
            )
        else:
            from cheapgpt_benchmarks.scoring import score_gpqa

            scores, summary = score_gpqa(records, scoring_key)
            complete_scores = summary["scored_attempts"] == summary["expected_attempts"]
        if scores != stored_scores or summary != stored_summary:
            raise ValueError("Deterministic score verification failed")
        if manifest.status == "completed" and not complete_scores:
            raise ValueError("Completed run has an incomplete score set")
    logical_attempts = {(item.benchmark, item.item_id, item.attempt) for item in records}
    completed_logical_attempts = {
        (item.benchmark, item.item_id, item.attempt)
        for item in records
        if item.status == "completed"
    }
    if len(completed_logical_attempts) != manifest.completed_logical_attempt_count:
        raise ValueError("Manifest logical attempt count does not match attempts")
    if (
        manifest.status == "completed"
        and len(completed_logical_attempts) != manifest.expected_logical_attempt_count
    ):
        raise ValueError("Completed run is missing logical attempts")
    return {"attempt_count": len(records), "logical_attempt_count": len(logical_attempts)}
