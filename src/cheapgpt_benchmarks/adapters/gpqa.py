import csv
import hashlib
import io
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from cheapgpt_benchmarks.plan import PlanItem

DATASET_URL = "https://openaipublic.blob.core.windows.net/simple-evals/gpqa_diamond.csv"
DATASET_SHA256 = "41d1213cd7a4998605a26c2798500652572007161b3a92817ba46b35befcd305"
CONTRACT_ID = "aa-gpqa-diamond-v4.1.1"
PROMPT = (
    "Answer the following multiple choice question. The last line of your response should be in "
    "the following format: 'Answer: A/B/C/D' (e.g. 'Answer: A').\n\n"
    "{question}\n\n"
    "A) {a}\n"
    "B) {b}\n"
    "C) {c}\n"
    "D) {d}"
)


@dataclass(frozen=True)
class GPQAContract:
    id: str
    plan: list[PlanItem]
    expected: dict[str, str]
    dataset_sha256: str


def _dataset(cache_root: Path) -> bytes:
    path = cache_root / "gpqa_diamond.csv"
    if not path.exists():
        response = httpx.get(DATASET_URL, follow_redirects=True, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != DATASET_SHA256:
        path.unlink(missing_ok=True)
        raise ValueError("GPQA Diamond dataset checksum mismatch")
    return payload


def prepare_gpqa(cache_root: Path, repeats: int = 5) -> GPQAContract:
    rows = list(csv.DictReader(io.StringIO(_dataset(cache_root).decode("utf-8"))))
    if len(rows) != 198:
        raise ValueError(f"Expected 198 GPQA Diamond rows, found {len(rows)}")

    rng = random.Random(0)
    plan: list[PlanItem] = []
    expected: dict[str, str] = {}
    for index, row in enumerate(rows * repeats):
        choices = [
            row["Correct Answer"],
            row["Incorrect Answer 1"],
            row["Incorrect Answer 2"],
            row["Incorrect Answer 3"],
        ]
        permutation = rng.sample(range(4), 4)
        shuffled = [choices[position] for position in permutation]
        answer = "ABCD"[shuffled.index(row["Correct Answer"])]
        repeat = index // len(rows) + 1
        item_id = f"gpqa-diamond-{row['Record ID']}-r{repeat}"
        plan.append(
            PlanItem(
                id=item_id,
                benchmark="gpqa-diamond",
                prompt=PROMPT.format(
                    question=row["Question"],
                    a=shuffled[0],
                    b=shuffled[1],
                    c=shuffled[2],
                    d=shuffled[3],
                ),
                parameters={
                    "max_output_tokens": 128000,
                    "store": False,
                    "temperature": 0.6,
                },
            )
        )
        expected[item_id] = answer
    return GPQAContract(CONTRACT_ID, plan, expected, DATASET_SHA256)


QUICK_PROMPT = (
    "What is the correct answer to this question: {question}\n\n"
    "Choices:\n"
    "(A) {a}\n"
    "(B) {b}\n"
    "(C) {c}\n"
    "(D) {d}\n\n"
    'Format your response as follows: "The correct answer is (insert answer here)"'
)


def build_gpqa_quick_plan(source: dict[str, Any], cache_root: Path) -> list[PlanItem]:
    rows = {
        row["Record ID"]: row
        for row in csv.DictReader(io.StringIO(_dataset(cache_root).decode("utf-8"), newline=""))
    }
    plan: list[PlanItem] = []
    for item in source["items"]:
        row = rows[item["record_id"]]
        a, b, c, d = (row[column] for column in item["choices"])
        plan.append(
            PlanItem(
                id=f"gpqa-diamond-{item['record_id']}",
                benchmark="gpqa-diamond",
                prompt=QUICK_PROMPT.format(question=row["Question"], a=a, b=b, c=c, d=d),
                parameters=source["parameters"],
            )
        )
    return plan
