import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cheapgpt_benchmarks.community import create_bundle, verify_bundle
from cheapgpt_benchmarks.models import RunManifest


def completed_run(root: Path) -> None:
    root.mkdir()
    manifest = RunManifest(
        run_id="2026-09-03.1",
        cli_version="0.1.0",
        profile="quick-v1",
        track="default",
        model="gpt-5.6-sol",
        reasoning_effort="low",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="completed",
        benchmark_lock_sha256="0" * 64,
        attempt_count=0,
        completed_count=0,
        error_count=0,
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (root / "attempts.jsonl").write_text("", encoding="utf-8")


def test_community_bundle_is_immutable_and_non_official(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    completed_run(run_root)
    bundle = create_bundle(run_root, tmp_path / "bundle", "@developer")

    metadata = verify_bundle(bundle)
    assert metadata["official"] is False
    assert metadata["author"] == "@developer"

    submission = json.loads((bundle / "submission.json").read_text())
    submission["official"] = True
    (bundle / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
    with pytest.raises(ValueError, match="official=false"):
        verify_bundle(bundle)
