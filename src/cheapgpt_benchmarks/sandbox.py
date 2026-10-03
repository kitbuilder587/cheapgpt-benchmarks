import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

SCORER_IMAGE = "ghcr.io/kitbuilder587/cheapgpt-benchmarks-scorer:5d3c086-28fef95"


def _clean_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
    }
    environment.update({"NO_PROXY": "*", "no_proxy": "*"})
    return environment


def _run(command: list[str]) -> None:
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, env=_clean_environment()
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Sandboxed scorer failed: {message}")


def ensure_scorer_image(docker_context: Path) -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is required to score LiveBench and LiveCodeBench")
    inspected = subprocess.run(
        ["docker", "image", "inspect", SCORER_IMAGE],
        check=False,
        capture_output=True,
    )
    if inspected.returncode:
        pulled = subprocess.run(
            ["docker", "pull", SCORER_IMAGE],
            check=False,
            capture_output=True,
            env=_clean_environment(),
        )
        if not pulled.returncode:
            return
        _run(
            [
                "docker",
                "build",
                "--file",
                str(docker_context / "Dockerfile.scorer"),
                "--tag",
                SCORER_IMAGE,
                str(docker_context),
            ]
        )


def sandbox_score_outputs(
    run_root: Path, quick_expected_root: Path, docker_context: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ensure_scorer_image(docker_context)
    with tempfile.TemporaryDirectory(prefix="cheapgpt-score-") as output:
        output_root = Path(output)
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=256",
                "--memory=4g",
                "--cpus=2",
                "--tmpfs=/tmp:rw,exec,nosuid,size=1g",
                "--volume",
                f"{run_root.resolve()}:/input:ro",
                "--volume",
                f"{quick_expected_root.resolve()}:/quick:ro",
                "--volume",
                f"{output_root.resolve()}:/output:rw",
                SCORER_IMAGE,
            ]
        )
        summary = cast(
            dict[str, Any],
            json.loads((output_root / "score-summary.json").read_text(encoding="utf-8")),
        )
        scores = [
            cast(dict[str, Any], json.loads(line))
            for line in (output_root / "scores.jsonl").read_text(encoding="utf-8").split("\n")
            if line
        ]
    return scores, summary


def score_quick_sandboxed(
    run_root: Path, quick_expected_root: Path, docker_context: Path
) -> dict[str, Any]:
    selected = {
        json.loads(line)["benchmark"]
        for line in (run_root / "attempts.jsonl").read_text(encoding="utf-8").split("\n")
        if line.strip()
    }
    if not selected.intersection({"livebench", "livecodebench"}):
        return cast(
            dict[str, Any],
            json.loads((run_root / "score-summary.json").read_text(encoding="utf-8")),
        )
    external_scores, external_summary = sandbox_score_outputs(
        run_root, quick_expected_root, docker_context
    )

    summary_path = run_root / "score-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["benchmarks"].update(
        {
            name: value
            for name, value in external_summary.items()
            if name in selected
        }
    )
    summary["scored_benchmarks"] = len(summary["benchmarks"])
    with (run_root / "scores.jsonl").open("a", encoding="utf-8") as scores_file:
        scores_file.write(
            "".join(
                json.dumps(score, ensure_ascii=False, sort_keys=True) + "\n"
                for score in external_scores
            )
        )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return cast(dict[str, Any], summary)
