import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cheapgpt_benchmarks.adapters import build_gpqa_quick_plan, build_hle_quick_plan
from cheapgpt_benchmarks.hashing import file_sha256
from cheapgpt_benchmarks.plan import PlanItem, load_plan

CHOICE_BENCHMARKS = {"gpqa-diamond", "hle", "mmlu-pro"}
GATED_PLAN_BUILDERS: dict[str, Callable[[dict[str, Any], Path], list[PlanItem]]] = {
    "gpqa-diamond": build_gpqa_quick_plan,
    "hle": lambda source, _cache_root: build_hle_quick_plan(source),
}


@dataclass(frozen=True)
class QuickAssets:
    plan: list[PlanItem]
    expected: dict[str, dict[str, dict[str, Any]]]


def serialize_plan(plan: list[PlanItem]) -> bytes:
    return "".join(
        json.dumps(item.model_dump(exclude_none=True), ensure_ascii=False) + "\n" for item in plan
    ).encode("utf-8")


def _gated_plan(root: Path, benchmark: str, cache_root: Path) -> tuple[list[PlanItem], str]:
    source = json.loads((root / "sources" / f"{benchmark}.json").read_text(encoding="utf-8"))
    plan = GATED_PLAN_BUILDERS[benchmark](source, cache_root)
    return plan, hashlib.sha256(serialize_plan(plan)).hexdigest()


def _bundled_plan(root: Path, benchmark: str) -> tuple[list[PlanItem], str]:
    plan_path = root / "plans" / f"{benchmark}.jsonl"
    return load_plan(plan_path), file_sha256(plan_path)


def load_quick_assets(root: Path, benchmarks: list[str], cache_root: Path) -> QuickAssets:
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    configured = manifest["benchmarks"]
    unknown = set(benchmarks).difference(configured)
    if unknown:
        raise ValueError(f"Unknown quick benchmark: {', '.join(sorted(unknown))}")
    plan: list[PlanItem] = []
    expected: dict[str, dict[str, dict[str, Any]]] = {}
    for benchmark in benchmarks:
        benchmark_manifest = configured[benchmark]
        expected_path = root / "expected" / f"{benchmark}.json"
        if benchmark in GATED_PLAN_BUILDERS:
            benchmark_plan, plan_sha256 = _gated_plan(root, benchmark, cache_root)
        else:
            benchmark_plan, plan_sha256 = _bundled_plan(root, benchmark)
        if plan_sha256 != benchmark_manifest["plan_sha256"]:
            raise ValueError(f"Quick plan hash mismatch: {benchmark}")
        if file_sha256(expected_path) != benchmark_manifest["expected_sha256"]:
            raise ValueError(f"Quick expected-data hash mismatch: {benchmark}")
        if len(benchmark_plan) != benchmark_manifest["items"]:
            raise ValueError(f"Quick item count mismatch: {benchmark}")
        plan.extend(benchmark_plan)
        if benchmark in CHOICE_BENCHMARKS:
            expected[benchmark] = json.loads(expected_path.read_text(encoding="utf-8"))
    return QuickAssets(plan=plan, expected=expected)
