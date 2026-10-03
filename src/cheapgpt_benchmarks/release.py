import gzip
import json
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from cheapgpt_benchmarks.hashing import file_sha256
from cheapgpt_benchmarks.models import RunManifest
from cheapgpt_benchmarks.verify import verify_run

RELEASE_ID = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*$")
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_ARTIFACTS = (
    "manifest.json",
    "scoring-key.json",
    "scores.jsonl",
    "score-summary.json",
    "report.html",
)


def _write_deterministic_gzip(source: Path, destination: Path) -> None:
    with source.open("rb") as input_file, destination.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as output_file:
            shutil.copyfileobj(input_file, output_file)


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name.capitalize()} is required for official releases")


def _safe_component(value: str) -> str:
    if not SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"Unsafe release filename component: {value!r}")
    return value


def _parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if separator != "  " or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid SHA256SUMS format")
        if not SAFE_COMPONENT.fullmatch(name) or name in checksums:
            raise ValueError(f"Unsafe or duplicate release artifact: {name!r}")
        checksums[name] = digest
    if not checksums:
        raise ValueError("SHA256SUMS is empty")
    return checksums


def prepare_release(
    run_roots: list[Path], output: Path, signing_key: Path
) -> dict[str, Any]:
    if not run_roots:
        raise ValueError("At least one run directory is required")
    if not RELEASE_ID.fullmatch(output.name):
        raise ValueError("Official release directory must use YYYY-MM-DD.N")
    if output.exists():
        raise FileExistsError(f"Release output already exists: {output}")
    if not signing_key.is_file():
        raise FileNotFoundError(f"Minisign secret key does not exist: {signing_key}")
    _require_tool("minisign")

    manifests = []
    prefixes: set[str] = set()
    for run_root in run_roots:
        verify_run(run_root)
        manifest = RunManifest.model_validate_json(
            (run_root / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest.status != "completed":
            raise ValueError(f"Official run is incomplete: {run_root}")
        missing = [
            name
            for name in ("attempts.jsonl", *RUN_ARTIFACTS)
            if not (run_root / name).is_file()
        ]
        if missing:
            raise ValueError(f"Official run is missing artifacts: {', '.join(missing)}")
        prefix = "-".join(
            _safe_component(value)
            for value in (manifest.model, manifest.profile, manifest.track, manifest.run_id)
        )
        if prefix in prefixes:
            raise ValueError(f"Duplicate official run identity: {prefix}")
        prefixes.add(prefix)
        manifests.append((run_root, manifest, prefix))

    output.mkdir(parents=True)
    files: dict[str, str] = {}
    runs = []
    for run_root, manifest, prefix in manifests:
        attempts_name = f"{prefix}-attempts.jsonl.gz"
        _write_deterministic_gzip(run_root / "attempts.jsonl", output / attempts_name)
        files[attempts_name] = file_sha256(output / attempts_name)
        copied = {}
        for artifact in RUN_ARTIFACTS:
            name = f"{prefix}-{artifact}"
            shutil.copy2(run_root / artifact, output / name)
            files[name] = file_sha256(output / name)
            copied[artifact] = name
        runs.append(
            {
                "run_id": manifest.run_id,
                "model": manifest.model,
                "profile": manifest.profile,
                "track": manifest.track,
                "reasoning_effort": manifest.reasoning_effort,
                "benchmark_contract": manifest.benchmark_contract,
                "dataset_sha256": manifest.dataset_sha256,
                "attempts": attempts_name,
                "artifacts": copied,
            }
        )

    index = {
        "schema_version": 1,
        "release_id": output.name,
        "official": True,
        "created_at": datetime.now(UTC).isoformat(),
        "runs": runs,
        "files": files,
    }
    index_path = output / "release.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    signed_files = {**files, "release.json": file_sha256(index_path)}
    checksum_path = output / "SHA256SUMS"
    checksum_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(signed_files.items())),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "minisign",
            "-S",
            "-s",
            str(signing_key),
            "-m",
            str(checksum_path),
            "-x",
            str(output / "SHA256SUMS.minisig"),
        ],
        check=True,
    )
    return index


def verify_release(root: Path, public_key: Path) -> dict[str, Any]:
    _require_tool("minisign")
    if not public_key.is_file():
        raise FileNotFoundError(f"Minisign public key does not exist: {public_key}")
    checksum_path = root / "SHA256SUMS"
    subprocess.run(
        [
            "minisign",
            "-V",
            "-p",
            str(public_key),
            "-m",
            str(checksum_path),
            "-x",
            str(root / "SHA256SUMS.minisig"),
        ],
        check=True,
    )
    checksums = _parse_checksums(checksum_path)
    actual_files = {
        path.name
        for path in root.iterdir()
        if path.is_file() and path.name not in {"SHA256SUMS", "SHA256SUMS.minisig"}
    }
    if actual_files != set(checksums):
        raise ValueError("Release artifact set does not match SHA256SUMS")
    for name, expected_hash in checksums.items():
        if file_sha256(root / name) != expected_hash:
            raise ValueError(f"Official release artifact hash mismatch: {name}")

    index = cast(
        dict[str, Any],
        json.loads((root / "release.json").read_text(encoding="utf-8")),
    )
    if index.get("schema_version") != 1 or index.get("official") is not True:
        raise ValueError("Invalid official release metadata")
    release_id = index.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID.fullmatch(release_id):
        raise ValueError("Invalid official release ID")
    if release_id != root.name:
        raise ValueError("Release ID does not match its directory")
    indexed_files = index.get("files")
    if not isinstance(indexed_files, dict) or indexed_files != {
        name: digest for name, digest in checksums.items() if name != "release.json"
    }:
        raise ValueError("release.json file index does not match SHA256SUMS")
    runs = index.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Official release contains no runs")

    referenced_files: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="cheapgpt-release-") as temporary:
        temporary_root = Path(temporary)
        for position, item in enumerate(runs):
            if not isinstance(item, dict):
                raise ValueError("Invalid run metadata in official release")
            run_root = temporary_root / str(position)
            run_root.mkdir()
            attempts = item.get("attempts")
            artifacts = item.get("artifacts")
            if not isinstance(attempts, str) or attempts not in indexed_files:
                raise ValueError("Official run has an invalid attempts artifact")
            referenced_files.add(attempts)
            if not isinstance(artifacts, dict) or set(artifacts) != set(RUN_ARTIFACTS):
                raise ValueError("Official run has an incomplete artifact map")
            with gzip.open(root / attempts, "rb") as source, (
                run_root / "attempts.jsonl"
            ).open("wb") as destination:
                shutil.copyfileobj(source, destination)
            for artifact, packaged_name in artifacts.items():
                if not isinstance(packaged_name, str) or packaged_name not in indexed_files:
                    raise ValueError(f"Official run has an invalid {artifact} artifact")
                referenced_files.add(packaged_name)
                shutil.copy2(root / packaged_name, run_root / artifact)
            manifest = RunManifest.model_validate_json(
                (run_root / "manifest.json").read_text(encoding="utf-8")
            )
            declared = (
                "run_id",
                "model",
                "profile",
                "track",
                "reasoning_effort",
                "benchmark_contract",
                "dataset_sha256",
            )
            if any(item.get(field) != getattr(manifest, field) for field in declared):
                raise ValueError("Official release metadata does not match its run manifest")
            verify_run(run_root)
    if referenced_files != set(indexed_files):
        raise ValueError("Official release contains unreferenced artifacts")
    return index


def _load_json_object(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def index_release(
    root: Path,
    public_key: Path,
    reference_matrix: Path,
    official_index: Path,
    leaderboard_index: Path,
    release_url: str,
) -> list[dict[str, Any]]:
    release = verify_release(root, public_key)
    matrix = cast(dict[str, Any], yaml.safe_load(reference_matrix.read_text(encoding="utf-8")))
    contracts = cast(dict[str, dict[str, Any]], matrix["contracts"])
    model_references = cast(dict[str, dict[str, Any]], matrix["models"])
    gates = {
        (item["model"], item["effort"], item["benchmark"]): item
        for item in cast(list[dict[str, Any]], matrix["run_gate"])
        if item["decision"] == "run"
    }
    timestamp = datetime.now(UTC).isoformat()
    release_id = str(release["release_id"])
    rows: list[dict[str, Any]] = []
    for run in cast(list[dict[str, Any]], release["runs"]):
        contract_id = run.get("benchmark_contract")
        effort = run.get("reasoning_effort")
        if not isinstance(contract_id, str) or contract_id not in contracts:
            raise ValueError("Official run has no approved benchmark contract")
        if not isinstance(effort, str):
            raise ValueError("Official run has no explicit reasoning effort")
        contract = contracts[contract_id]
        benchmark = str(contract["benchmark"])
        gate = gates.get((run["model"], effort, benchmark))
        if gate is None or gate.get("contract") != contract_id:
            raise ValueError("Official run is not allowed by the reference gate")
        summary_name = run["artifacts"]["score-summary.json"]
        summary = _load_json_object(root / summary_name)
        if summary.get("benchmark") != benchmark:
            raise ValueError("Score summary does not match the benchmark contract")
        score = summary.get("score")
        if not isinstance(score, int | float):
            raise ValueError("Official score summary has no numeric score")
        reference_key = "gpqa" if benchmark == "gpqa-diamond" else benchmark
        reference_value = model_references[run["model"]]["efforts"][effort][reference_key]
        questions = summary.get("questions") or summary.get("problems")
        attempts = summary.get("scored_attempts") or summary.get("scored")
        if not isinstance(questions, int) or questions < 1:
            raise ValueError("Official score summary has no question count")
        if not isinstance(attempts, int) or attempts < 1:
            raise ValueError("Official score summary has no scored attempt count")
        primary_url = str(gate["reference_url"])
        snapshot_url = str(gate["snapshot_url"])
        rows.append(
            {
                "id": f"{release_id}:{run['run_id']}:{run['model']}:{benchmark}",
                "run_type": "official",
                "provider": "CheapGPT",
                "model": run["model"],
                "benchmark": benchmark,
                "reasoning_effort": effort,
                "dataset_release": contract_id,
                "scoring_contract": contract_id,
                "questions": questions,
                "attempts": attempts,
                "score": {"value": float(score), "unit": "percent"},
                "reference": {
                    "source": contract["source"],
                    "value": float(reference_value) * 100,
                    "url": primary_url,
                    "snapshot_url": snapshot_url,
                    "compatible": True,
                },
                "artifact_url": release_url,
                "published_at": timestamp,
            }
        )

    official = _load_json_object(official_index)
    retained_official = [
        row
        for row in cast(list[dict[str, Any]], official["runs"])
        if not str(row.get("id", "")).startswith(f"{release_id}:")
    ]
    official["latest_verified_run"] = release_id
    official["runs"] = [*retained_official, *rows]
    official_index.write_text(
        json.dumps(official, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    leaderboard = _load_json_object(leaderboard_index)
    retained_rows = [
        row
        for row in cast(list[dict[str, Any]], leaderboard["rows"])
        if not (
            row.get("run_type") == "official"
            and str(row.get("id", "")).startswith(f"{release_id}:")
        )
    ]
    leaderboard["updated_at"] = timestamp
    leaderboard["rows"] = [*retained_rows, *rows]
    leaderboard_index.write_text(
        json.dumps(leaderboard, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows
