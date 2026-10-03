import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from cheapgpt_benchmarks.models import RunManifest
from cheapgpt_benchmarks.release import index_release, prepare_release, verify_release
from cheapgpt_benchmarks.scoring import score_gpqa


def create_completed_run(root: Path) -> Path:
    run = root / "run"
    run.mkdir()
    manifest = RunManifest(
        run_id="2026-09-03.1",
        cli_version="0.1.0",
        profile="full-v1",
        track="leaderboard",
        model="gpt-5.6-sol",
        reasoning_effort="low",
        benchmark_contract="aa-gpqa-diamond-v4.1.1",
        dataset_sha256="1" * 64,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="completed",
        benchmark_lock_sha256="0" * 64,
        attempt_count=0,
        completed_count=0,
        error_count=0,
    )
    (run / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (run / "attempts.jsonl").write_text("", encoding="utf-8")
    (run / "scoring-key.json").write_text("{}\n", encoding="utf-8")
    (run / "scores.jsonl").write_text("", encoding="utf-8")
    _, summary = score_gpqa([], {})
    (run / "score-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run / "report.html").write_text("<!doctype html>", encoding="utf-8")
    return run


def fake_minisign(command: list[str], check: bool) -> None:
    assert check is True
    if "-S" in command:
        Path(command[-1]).write_text("signature", encoding="utf-8")


def test_prepare_and_verify_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = create_completed_run(tmp_path)
    secret_key = tmp_path / "minisign.key"
    secret_key.write_text("fixture", encoding="utf-8")
    public_key = tmp_path / "minisign.pub"
    public_key.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("cheapgpt_benchmarks.release.shutil.which", lambda _: "minisign")
    monkeypatch.setattr("cheapgpt_benchmarks.release.subprocess.run", fake_minisign)

    output = tmp_path / "2026-09-03.1"
    release = prepare_release([run], output, secret_key)

    assert release["official"] is True
    compressed = next(output.glob("*-attempts.jsonl.gz"))
    assert gzip.decompress(compressed.read_bytes()) == b""
    assert "release.json" not in release["files"]
    assert (output / "SHA256SUMS.minisig").read_text() == "signature"
    assert verify_release(output, public_key) == release
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas/official-release.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(release)


def test_verify_release_rejects_a_changed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = create_completed_run(tmp_path)
    secret_key = tmp_path / "minisign.key"
    secret_key.write_text("fixture", encoding="utf-8")
    public_key = tmp_path / "minisign.pub"
    public_key.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("cheapgpt_benchmarks.release.shutil.which", lambda _: "minisign")
    monkeypatch.setattr("cheapgpt_benchmarks.release.subprocess.run", fake_minisign)
    output = tmp_path / "2026-09-03.1"
    release = prepare_release([run], output, secret_key)
    artifact = output / next(iter(release["files"]))
    artifact.write_bytes(artifact.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="hash mismatch"):
        verify_release(output, public_key)


def test_prepare_release_requires_canonical_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cheapgpt_benchmarks.release.shutil.which", lambda _: "minisign")
    key = tmp_path / "minisign.key"
    key.write_text("fixture", encoding="utf-8")

    with pytest.raises(ValueError, match=r"YYYY-MM-DD\.N"):
        prepare_release([tmp_path], tmp_path / "latest", key)


def test_index_release_derives_official_leaderboard_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_root = tmp_path / "2026-09-03.1"
    release_root.mkdir()
    (release_root / "summary.json").write_text(
        json.dumps(
            {
                "benchmark": "gpqa-diamond",
                "questions": 198,
                "scored_attempts": 990,
                "score": 90.101,
            }
        ),
        encoding="utf-8",
    )
    release = {
        "release_id": release_root.name,
        "runs": [
            {
                "run_id": "2026-09-03.1",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "low",
                "benchmark_contract": "aa-gpqa",
                "artifacts": {"score-summary.json": "summary.json"},
            }
        ],
    }
    monkeypatch.setattr(
        "cheapgpt_benchmarks.release.verify_release", lambda _root, _key: release
    )
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text(
        """contracts:
  aa-gpqa:
    benchmark: gpqa-diamond
    source: Artificial Analysis
models:
  gpt-5.6-sol:
    efforts:
      low: {gpqa: 0.897979797979798}
run_gate:
  - model: gpt-5.6-sol
    effort: low
    benchmark: gpqa-diamond
    contract: aa-gpqa
    decision: run
    reference_url: https://example.test/reference
    snapshot_url: https://example.test/snapshot
""",
        encoding="utf-8",
    )
    official = tmp_path / "official.json"
    official.write_text(
        '{"schema_version":1,"latest_verified_run":null,"runs":[]}\n', encoding="utf-8"
    )
    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        '{"schema_version":1,"updated_at":null,"providers":["CheapGPT","Ромарио","Польза","GPTunnel"],"rows":[]}\n',
        encoding="utf-8",
    )

    rows = index_release(
        release_root,
        tmp_path / "public.key",
        matrix,
        official,
        leaderboard,
        "https://example.test/releases/2026-09-03.1",
    )

    assert rows[0]["score"] == {"value": 90.101, "unit": "percent"}
    assert rows[0]["reference"]["value"] == pytest.approx(89.7979797979798)
    official_data = json.loads(official.read_text())
    assert official_data["latest_verified_run"] == "2026-09-03.1"
    leaderboard_data = json.loads(leaderboard.read_text())
    assert leaderboard_data["rows"] == rows
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas/leaderboard-index.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(leaderboard_data)
    official_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas/release-index.schema.json").read_text()
    )
    Draft202012Validator(
        official_schema, format_checker=FormatChecker()
    ).validate(official_data)
