import json
import math
import re
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from cheapgpt_benchmarks.models import AttemptRecord

PRIMARY_PATTERN = re.compile(
    r"(?i)[*_]{0,2}Answer[*_]{0,2}\s*:[\s*_]{0,2}\s*([A-D])(?![a-zA-Z0-9])"
)
FALLBACK_PATTERNS = (
    re.compile(r"\\boxed\{[^}]*([A-D])[^}]*\}", re.IGNORECASE),
    re.compile(r"answer is ([A-D])", re.IGNORECASE),
    re.compile(r"answer is \(([A-D])", re.IGNORECASE),
    re.compile(r"([A-D])\)\s*[^A-D]*", re.IGNORECASE),
    re.compile(r"([A-D])\s+is\s+the\s+correct\s+answer", re.IGNORECASE),
    re.compile(r"([A-D])\s*$", re.IGNORECASE),
    re.compile(r"([A-D])\s*\.\s*$", re.IGNORECASE),
)


def output_text(body: dict[str, Any] | None) -> str:
    chunks: list[str] = []
    for output in (body or {}).get("output", []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    return "\n".join(chunks)


def extract_gpqa_answer(text: str) -> str | None:
    stripped = text.strip()
    if re.fullmatch(r"[A-D]", stripped, re.IGNORECASE):
        return stripped.upper()
    for pattern in (PRIMARY_PATTERN, *FALLBACK_PATTERNS):
        matches = pattern.findall(text)
        if matches:
            return str(matches[-1]).upper()
    return None


def extract_choice_answer(text: str, alphabet: str) -> str | None:
    escaped = re.escape(alphabet)
    patterns = (
        re.compile(rf"(?i)the correct answer is\s*\(?([{escaped}])\)?"),
        re.compile(rf"(?i)answer\s*:\s*\(?([{escaped}])\)?"),
        re.compile(rf"\(([{escaped}])\)"),
        re.compile(rf"([{escaped}])\s*$", re.IGNORECASE),
    )
    for pattern in patterns:
        matches = pattern.findall(text)
        if matches:
            return str(matches[-1]).upper()
    return None


def _arc_grid(candidate: object) -> list[list[int]] | None:
    if not isinstance(candidate, list) or not candidate:
        return None
    if not all(isinstance(row, list) for row in candidate):
        return None
    try:
        return TypeAdapter(list[list[int]]).validate_python(candidate)
    except ValidationError:
        return None


def extract_arc_grid(text: str) -> list[list[int]] | None:
    boxed = re.search(r"\\boxed\{(.*?)\}", text, re.DOTALL)
    if boxed:
        try:
            candidate = json.loads(boxed.group(1).strip())
        except json.JSONDecodeError:
            pass
        else:
            grid = _arc_grid(candidate)
            if grid is not None:
                return grid

    end = max(text.rfind("]"), text.rfind("}"))
    if end < 0:
        return None
    closing = text[end]
    opening = "[" if closing == "]" else "{"
    depth = 1
    for start in range(end - 1, -1, -1):
        if text[start] == closing:
            depth += 1
        elif text[start] == opening:
            depth -= 1
            if depth == 0:
                try:
                    candidate = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
                return _arc_grid(candidate)
    return None


def _wilson(correct: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    proportion = correct / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return center - margin, center + margin


def score_gpqa(
    records: list[AttemptRecord], expected: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    completed: dict[tuple[str, int], AttemptRecord] = {}
    for record in records:
        if record.status == "completed" and record.item_id in expected:
            completed[(record.item_id, record.attempt)] = record

    scores: list[dict[str, Any]] = []
    for (item_id, attempt), record in sorted(completed.items()):
        prediction = extract_gpqa_answer(output_text(record.response.body))
        answer = expected[item_id]
        scores.append(
            {
                "item_id": item_id,
                "attempt": attempt,
                "prediction": prediction,
                "answer": answer,
                "score": int(prediction == answer),
                "source_content_sha256": record.content_sha256,
            }
        )
    correct = sum(int(item["score"]) for item in scores)
    lower, upper = _wilson(correct, len(scores))
    summary = {
        "benchmark": "gpqa-diamond",
        "metric": "pass@1",
        "questions": 198,
        "repeats": 5,
        "expected_attempts": len(expected),
        "scored_attempts": len(scores),
        "correct_attempts": correct,
        "score": round(correct / len(scores) * 100, 3) if scores else None,
        "confidence_interval_95": [round(lower * 100, 3), round(upper * 100, 3)],
    }
    return scores, summary


def write_gpqa_scores(
    root: Path, records: list[AttemptRecord], expected: dict[str, str]
) -> dict[str, Any]:
    scores, summary = score_gpqa(records, expected)
    (root / "scoring-key.json").write_text(
        json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "scores.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in scores),
        encoding="utf-8",
    )
    (root / "score-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def score_arc_agi_2(
    records: list[AttemptRecord], expected: dict[str, dict[str, object]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    pair_scores: dict[str, list[int]] = {}
    completed: dict[tuple[str, int], AttemptRecord] = {}
    for record in records:
        if record.status == "completed" and record.item_id in expected:
            completed[(record.item_id, record.attempt)] = record
    for (item_id, attempt), record in sorted(completed.items()):
        prediction = extract_arc_grid(output_text(record.response.body))
        item = expected[item_id]
        answer = item["answer"]
        score = int(prediction == answer)
        pair_scores.setdefault(item_id, []).append(score)
        scores.append(
            {
                "benchmark": "arc-agi-2",
                "item_id": item_id,
                "task_id": item["task_id"],
                "pair_index": item["pair_index"],
                "attempt": attempt,
                "prediction": prediction,
                "answer": answer,
                "score": score,
                "source_content_sha256": record.content_sha256,
            }
        )

    task_pairs: dict[str, list[int]] = {}
    for item_id, item in expected.items():
        pair_pass = int(any(pair_scores.get(item_id, [])))
        task_pairs.setdefault(str(item["task_id"]), []).append(pair_pass)
    task_scores = {
        task_id: sum(values) / len(values) for task_id, values in sorted(task_pairs.items())
    }
    overall = sum(task_scores.values()) / len(task_scores) if task_scores else 0.0
    summary = {
        "benchmark": "arc-agi-2",
        "metric": "official two-attempt task accuracy",
        "tasks": len(task_scores),
        "test_pairs": len(expected),
        "attempts_per_pair": 2,
        "expected_attempts": len(expected) * 2,
        "scored_attempts": len(scores),
        "solved_tasks": sum(score == 1 for score in task_scores.values()),
        "partial_tasks": sum(0 < score < 1 for score in task_scores.values()),
        "score": round(overall * 100, 3),
        "task_scores": task_scores,
    }
    return scores, summary


def write_arc_agi_2_scores(
    root: Path,
    records: list[AttemptRecord],
    expected: dict[str, dict[str, object]],
) -> dict[str, Any]:
    scores, summary = score_arc_agi_2(records, expected)
    (root / "scoring-key.json").write_text(
        json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "scores.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in scores),
        encoding="utf-8",
    )
    (root / "score-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def score_choice_benchmark(
    records: list[AttemptRecord],
    expected: dict[str, dict[str, Any]],
    benchmark: str,
    alphabet: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for record in records:
        if record.status != "completed" or record.benchmark != benchmark:
            continue
        answer = str(expected[record.item_id]["answer"])
        prediction = extract_choice_answer(output_text(record.response.body), alphabet)
        scores.append(
            {
                "benchmark": benchmark,
                "item_id": record.item_id,
                "attempt": record.attempt,
                "prediction": prediction,
                "answer": answer,
                "score": int(prediction == answer),
                "source_content_sha256": record.content_sha256,
            }
        )

    by_item: dict[str, list[int]] = {}
    for item in scores:
        by_item.setdefault(str(item["item_id"]), []).append(int(item["score"]))
    majority = [int(sum(values) > len(values) / 2) for values in by_item.values()]
    lower, upper = _wilson(sum(majority), len(majority))
    summary = {
        "benchmark": benchmark,
        "questions": len(expected),
        "attempts_per_item": 3,
        "scored_attempts": len(scores),
        "attempt_accuracy": round(sum(int(item["score"]) for item in scores) / len(scores) * 100, 3)
        if scores
        else None,
        "score": round(sum(majority) / len(majority) * 100, 3) if majority else None,
        "confidence_interval_95": [round(lower * 100, 3), round(upper * 100, 3)],
        "flapping_items": sum(len(set(values)) > 1 for values in by_item.values()),
    }
    return scores, summary


def write_quick_choice_scores(
    root: Path,
    records: list[AttemptRecord],
    expected_by_benchmark: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    alphabets = {"gpqa-diamond": "ABCD", "hle": "ABCDEFGHIJ", "mmlu-pro": "ABCDEFGHIJ"}
    all_scores: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for benchmark, expected in expected_by_benchmark.items():
        scores, summary = score_choice_benchmark(records, expected, benchmark, alphabets[benchmark])
        all_scores.extend(scores)
        summaries[benchmark] = summary
    result = {
        "profile": "quick-v1",
        "benchmarks": summaries,
        "scored_benchmarks": len(summaries),
        "expected_benchmarks": len({record.benchmark for record in records}),
    }
    (root / "scoring-key.json").write_text(
        json.dumps(expected_by_benchmark, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "scores.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in all_scores),
        encoding="utf-8",
    )
    (root / "score-summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
