import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_reference_matrix_matches_v1_models() -> None:
    matrix = yaml.safe_load((ROOT / "references/matrix.yaml").read_text())
    schema = json.loads((ROOT / "schemas/reference-matrix.schema.json").read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        matrix
    )

    configured = yaml.safe_load((ROOT / "models.yaml").read_text())["models"]
    configured_defaults = {item["id"]: item["default_effort"] for item in configured}
    matrix_defaults = {
        model: details["default_effort"] for model, details in matrix["models"].items()
    }
    assert configured_defaults == matrix_defaults

    runnable = matrix["run_gate"]
    assert {item["model"] for item in runnable if item["decision"] == "run"} == set(
        configured_defaults
    )
    assert all(
        item["effort"] == configured_defaults[item["model"]]
        for item in runnable
        if item["decision"] == "run"
    )
    benchmarks = {"livebench", "hle", "gpqa-diamond", "mmlu-pro", "livecodebench"}
    combinations = {(item["model"], item["benchmark"]) for item in runnable}
    assert len(runnable) == len(configured_defaults) * len(benchmarks)
    assert combinations == {
        (model, benchmark) for model in configured_defaults for benchmark in benchmarks
    }
    assert len(combinations) == len(runnable)
    assert all(item["reference_url"] for item in runnable if item["decision"] == "run")
    assert all(item["snapshot_url"] for item in runnable if item["decision"] == "run")
