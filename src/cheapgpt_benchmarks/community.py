import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cheapgpt_benchmarks.hashing import file_sha256
from cheapgpt_benchmarks.models import RunManifest

ARTIFACTS = (
    "manifest.json",
    "attempts.jsonl",
    "scoring-key.json",
    "scores.jsonl",
    "score-summary.json",
    "report.html",
)


def create_bundle(run_root: Path, output: Path, author: str) -> Path:
    if output.exists():
        raise FileExistsError(f"Bundle output already exists: {output}")
    run = RunManifest.model_validate_json((run_root / "manifest.json").read_text())
    if run.status != "completed":
        raise ValueError("Only completed runs can be submitted")
    output.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for name in ARTIFACTS:
        source = run_root / name
        if source.exists():
            shutil.copy2(source, output / name)
            hashes[name] = file_sha256(output / name)
    metadata = {
        "schema_version": 1,
        "kind": "community",
        "official": False,
        "submission_id": f"{run.run_id}-{run.model}-{author.lstrip('@')}",
        "author": author,
        "created_at": datetime.now(UTC).isoformat(),
        "run": {
            "run_id": run.run_id,
            "model": run.model,
            "profile": run.profile,
            "track": run.track,
            "reasoning_effort": run.reasoning_effort,
        },
        "files": hashes,
    }
    (output / "submission.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def verify_bundle(root: Path) -> dict[str, Any]:
    metadata = cast(
        dict[str, Any],
        json.loads((root / "submission.json").read_text(encoding="utf-8")),
    )
    if metadata.get("kind") != "community" or metadata.get("official") is not False:
        raise ValueError("Community bundle must be permanently marked official=false")
    files = metadata.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Community bundle contains no artifact hashes")
    if set(files).difference(ARTIFACTS):
        raise ValueError("Community bundle contains an unsupported artifact")
    for name, expected_hash in files.items():
        path = root / name
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise ValueError(f"Community artifact hash mismatch: {name}")
    run = RunManifest.model_validate_json((root / "manifest.json").read_text())
    declared_run = metadata.get("run", {})
    if declared_run.get("run_id") != run.run_id or declared_run.get("model") != run.model:
        raise ValueError("Community metadata does not match the run manifest")
    from cheapgpt_benchmarks.verify import verify_run

    verify_run(root)
    return metadata
