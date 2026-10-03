import argparse
import gzip
import json
import shutil
import tempfile
from pathlib import Path

from cheapgpt_benchmarks.hashing import file_sha256
from cheapgpt_benchmarks.release import RUN_ARTIFACTS, _write_deterministic_gzip
from cheapgpt_benchmarks.verify import verify_run

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "results"
ARTIFACTS = ("attempts.jsonl.gz", *RUN_ARTIFACTS)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def describe(root: Path) -> dict:
    verify_run(root)
    manifest = load(root / "manifest.json")
    if manifest["status"] != "completed":
        raise ValueError("Only completed runs can be exported")
    records = [json.loads(line) for line in (root / "attempts.jsonl").read_text().splitlines()]
    completed = [r for r in records if r["status"] == "completed"]
    return {
        "schema_version": 1,
        "provider": "CheapGPT",
        "official": False,
        "verification": "deterministic-rescore",
        "manifest": manifest,
        "summary": load(root / "score-summary.json"),
        "usage": {
            "input_tokens": sum(r["usage"]["input_tokens"] or 0 for r in completed),
            "output_tokens": sum(r["usage"]["output_tokens"] or 0 for r in completed),
            "reasoning_tokens": sum(
                r["usage"]["details"].get("output_tokens_details", {}).get("reasoning_tokens", 0)
                for r in completed
            ),
        },
        "transport": {
            mode: {
                status: sum(
                    r["status"] == status and bool(r["request"]["body"].get("stream")) == stream
                    for r in records
                )
                for status in ("completed", "error")
            }
            for mode, stream in (("nonstream", False), ("stream", True))
        },
    }


def export(source: Path) -> None:
    result = describe(source)
    run_id = result["manifest"]["run_id"]
    if source.name != run_id:
        raise ValueError("Directory must match the run ID")
    destination = PUBLIC / run_id
    destination.mkdir(parents=True, exist_ok=False)
    _write_deterministic_gzip(source / "attempts.jsonl", destination / "attempts.jsonl.gz")
    for name in RUN_ARTIFACTS:
        shutil.copy2(source / name, destination / name)
    result["artifacts"] = {name: file_sha256(destination / name) for name in ARTIFACTS}
    (PUBLIC / "index.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    check()


def check() -> None:
    published = load(PUBLIC / "index.json")
    run_id = published["manifest"]["run_id"]
    if Path(run_id).name != run_id:
        raise ValueError("Invalid public run ID")
    destination = PUBLIC / run_id
    if set(published["artifacts"]) != set(ARTIFACTS):
        raise ValueError("Incomplete artifact set")
    if {p.name for p in destination.iterdir()} != set(ARTIFACTS):
        raise ValueError("Unexpected public run files")
    if {p.name for p in PUBLIC.iterdir()} != {run_id, "index.json"}:
        raise ValueError("Public results must contain only the selected run")
    for name, digest in published["artifacts"].items():
        if file_sha256(destination / name) != digest:
            raise ValueError(f"Artifact checksum mismatch: {name}")
    with tempfile.TemporaryDirectory(prefix="cheapgpt-public-check-") as temp:
        root = Path(temp)
        for name in RUN_ARTIFACTS:
            shutil.copy2(destination / name, root / name)
        with gzip.open(destination / "attempts.jsonl.gz", "rb") as source:
            with (root / "attempts.jsonl").open("wb") as target:
                shutil.copyfileobj(source, target)
        expected = describe(root)
        actual = {k: v for k, v in published.items() if k != "artifacts"}
        if expected != actual:
            raise ValueError("Public index disagrees with verified run")
    print(f"Verified public result {run_id}: {published['summary']['score']}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export one local run; never uploads results")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
    elif args.source:
        export(args.source)
    else:
        parser.error("Provide a source run or --check")
