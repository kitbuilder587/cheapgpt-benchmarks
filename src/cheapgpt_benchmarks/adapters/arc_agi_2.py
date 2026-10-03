import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from cheapgpt_benchmarks.plan import PlanItem

DATASET_COMMIT = "f3283f727488ad98fe575ea6a5ac981e4a188e49"
DATASET_URL = f"https://codeload.github.com/arcprize/ARC-AGI-2/tar.gz/{DATASET_COMMIT}"
DATASET_SHA256 = "179681bc01d55810ee0e90d2717ef04b8d130496541c4853479a8d6fffa4b975"
CONTRACT_ID = "arc-prize-arc-agi-2-public-eval-text-v1"
TASK_PATH = re.compile(r"^[^/]+/data/evaluation/([0-9a-f]{8})\.json$")
PROMPT = (
    "You are participating in a puzzle solving competition. You are an expert at solving "
    "puzzles.\n\n"
    "Below is a list of input and output pairs with a pattern. Your goal is to identify the "
    "pattern or transformation in the training examples that maps the input to the output, then "
    "apply that pattern to the test input to give a final output.\n\n"
    "Respond in the format of the training output examples\n\n"
    "--Training Examples--\n"
    "{training_examples}\n--End of Training Examples--\n\n"
    "--Test Input--\n"
    "{test_input}\n"
    "--End of Test Input--\n\n"
    "Your response:"
)


@dataclass(frozen=True)
class ARCAGI2Contract:
    id: str
    plan: list[PlanItem]
    expected: dict[str, dict[str, Any]]
    dataset_sha256: str


def _dataset(cache_root: Path) -> bytes:
    path = cache_root / f"arc-agi-2-{DATASET_COMMIT}.tar.gz"
    if not path.exists():
        response = httpx.get(DATASET_URL, follow_redirects=True, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != DATASET_SHA256:
        path.unlink(missing_ok=True)
        raise ValueError("ARC-AGI-2 dataset checksum mismatch")
    return payload


def _tasks(payload: bytes) -> list[tuple[str, dict[str, Any]]]:
    tasks: list[tuple[str, dict[str, Any]]] = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            match = TASK_PATH.fullmatch(member.name)
            if not member.isfile() or match is None:
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Cannot read ARC-AGI-2 task {member.name}")
            tasks.append((match.group(1), json.load(source)))
    if len(tasks) != 120:
        raise ValueError(f"Expected 120 ARC-AGI-2 evaluation tasks, found {len(tasks)}")
    return tasks


def _prompt(training_pairs: list[dict[str, Any]], test_input: list[list[int]]) -> str:
    examples = ""
    for index, pair in enumerate(training_pairs):
        examples += f"--Example {index}-- \n\n INPUT: \n\n"
        examples += json.dumps(pair["input"]) + "\n\n"
        examples += "OUTPUT: \n\n"
        examples += json.dumps(pair["output"]) + "\n\n"
    return PROMPT.format(training_examples=examples, test_input=json.dumps(test_input))


def prepare_arc_agi_2(cache_root: Path) -> ARCAGI2Contract:
    plan: list[PlanItem] = []
    expected: dict[str, dict[str, Any]] = {}
    for task_id, task in _tasks(_dataset(cache_root)):
        training_pairs = task.get("train")
        test_pairs = task.get("test")
        if not isinstance(training_pairs, list) or not isinstance(test_pairs, list):
            raise ValueError(f"Invalid ARC-AGI-2 task {task_id}")
        for pair_index, pair in enumerate(test_pairs):
            item_id = f"arc-agi-2-{task_id}-p{pair_index + 1}"
            plan.append(
                PlanItem(
                    id=item_id,
                    benchmark="arc-agi-2",
                    prompt=_prompt(training_pairs, pair["input"]),
                    parameters={"max_output_tokens": 128000, "store": False},
                    attempts=2,
                )
            )
            expected[item_id] = {
                "task_id": task_id,
                "pair_index": pair_index,
                "answer": pair["output"],
            }
    if len(plan) != 167:
        raise ValueError(f"Expected 167 ARC-AGI-2 test pairs, found {len(plan)}")
    return ARCAGI2Contract(CONTRACT_ID, plan, expected, DATASET_SHA256)
