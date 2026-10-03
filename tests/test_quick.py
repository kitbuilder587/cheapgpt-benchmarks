import csv
import io
from pathlib import Path
from typing import Any

import pytest

from cheapgpt_benchmarks import quick
from cheapgpt_benchmarks.adapters import gpqa
from cheapgpt_benchmarks.adapters.hle import build_hle_quick_plan
from cheapgpt_benchmarks.plan import PlanItem
from cheapgpt_benchmarks.quick import load_quick_assets

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ["livebench", "mmlu-pro", "livecodebench"]


def test_bundled_quick_assets_are_pinned_and_complete(tmp_path: Path) -> None:
    assets = load_quick_assets(ROOT / "quick", BUNDLED, tmp_path)

    assert len(assets.plan) == 16
    assert {item.benchmark for item in assets.plan} == set(BUNDLED)
    assert set(assets.expected) == {"mmlu-pro"}


def test_gated_benchmarks_are_not_bundled_in_plain_text() -> None:
    assert not (ROOT / "quick" / "plans" / "gpqa-diamond.jsonl").exists()
    assert not (ROOT / "quick" / "plans" / "hle.jsonl").exists()


def test_gated_plan_must_match_pinned_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tampered(source: dict[str, Any], _cache: Path) -> list[PlanItem]:
        return [
            PlanItem(id=f"hle-{item_id}", benchmark="hle", prompt="changed")
            for item_id in source["items"]
        ]

    monkeypatch.setitem(quick.GATED_PLAN_BUILDERS, "hle", tampered)

    with pytest.raises(ValueError, match="Quick plan hash mismatch: hle"):
        load_quick_assets(ROOT / "quick", ["hle"], tmp_path)


def test_hle_requires_hugging_face_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(ValueError, match="HF_TOKEN"):
        build_hle_quick_plan({"dataset": "cais/hle", "items": ["a"], "parameters": {}})


def test_gpqa_quick_plan_uses_recorded_choice_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = io.StringIO()
    writer = csv.DictWriter(
        rows,
        fieldnames=[
            "Record ID",
            "Question",
            "Correct Answer",
            "Incorrect Answer 1",
            "Incorrect Answer 2",
            "Incorrect Answer 3",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "Record ID": "rec1",
            "Question": "Q?",
            "Correct Answer": "right",
            "Incorrect Answer 1": "w1",
            "Incorrect Answer 2": "w2",
            "Incorrect Answer 3": "w3",
        }
    )
    monkeypatch.setattr(gpqa, "_dataset", lambda _cache: rows.getvalue().encode())
    source = {
        "parameters": {"store": False},
        "items": [
            {
                "record_id": "rec1",
                "choices": [
                    "Incorrect Answer 2",
                    "Correct Answer",
                    "Incorrect Answer 3",
                    "Incorrect Answer 1",
                ],
            }
        ],
    }

    [item] = gpqa.build_gpqa_quick_plan(source, tmp_path)

    assert item.id == "gpqa-diamond-rec1"
    assert "(A) w2\n(B) right\n(C) w3\n(D) w1" in item.prompt
    assert item.parameters == {"store": False}
