import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml
from rich.console import Console
from rich.table import Table

from cheapgpt_benchmarks import __version__
from cheapgpt_benchmarks.adapters import prepare_arc_agi_2, prepare_gpqa
from cheapgpt_benchmarks.community import create_bundle, verify_bundle
from cheapgpt_benchmarks.constants import DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS
from cheapgpt_benchmarks.plan import load_plan
from cheapgpt_benchmarks.profile import load_profile
from cheapgpt_benchmarks.quick import load_quick_assets
from cheapgpt_benchmarks.release import index_release, prepare_release, verify_release
from cheapgpt_benchmarks.runner import run_plan

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
console = Console()


def repository_file(name: str) -> Path:
    candidates = [
        Path.cwd() / name,
        Path(__file__).resolve().parent / name,
        Path(__file__).resolve().parents[2] / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise typer.BadParameter(f"Cannot locate {name}; run from a repository checkout")


def default_effort(model: str) -> str:
    configured = yaml.safe_load(repository_file("models.yaml").read_text(encoding="utf-8"))
    efforts = {item["id"]: item["default_effort"] for item in configured["models"]}
    if model not in efforts:
        raise typer.BadParameter(f"Unsupported V1 model: {model}")
    return str(efforts[model])


@app.command()
def version() -> None:
    """Print the runner version."""
    console.print(__version__)


@app.command()
def doctor() -> None:
    """Check local prerequisites without making API requests."""
    table = Table(title="CheapGPT Benchmarks · doctor")
    table.add_column("Check")
    table.add_column("Status")
    checks = {
        "CHEAPGPT_API_KEY": bool(os.getenv("CHEAPGPT_API_KEY")),
        "HF_TOKEN (HLE quick items)": bool(os.getenv("HF_TOKEN")),
        "Docker": shutil.which("docker") is not None,
        "Git": shutil.which("git") is not None,
        "Minisign (maintainers)": shutil.which("minisign") is not None,
        "SOPS (canary maintainers)": shutil.which("sops") is not None,
    }
    for name, available in checks.items():
        table.add_row(name, "[green]ready[/green]" if available else "[yellow]missing[/yellow]")
    console.print(table)


@app.command()
def run(
    model: Annotated[str, typer.Option(help="Exact CheapGPT model identifier")],
    profile: Annotated[Literal["quick", "full"], typer.Option()] = "quick",
    track: Annotated[Literal["default", "leaderboard"], typer.Option()] = "default",
    plan: Annotated[
        Path | None,
        typer.Option(help="Validated request plan emitted by an official harness adapter"),
    ] = None,
    benchmark: Annotated[
        Literal["arc-agi-2", "livebench", "hle", "gpqa-diamond", "mmlu-pro", "livecodebench"]
        | None,
        typer.Option(help="Run one benchmark from the selected profile"),
    ] = None,
    effort: Annotated[
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None,
        typer.Option(help="Reasoning effort; defaults to the CheapGPT V1 configuration"),
    ] = None,
    output: Annotated[Path, typer.Option()] = Path("runs"),
    resume: Annotated[Path | None, typer.Option(help="Resume an incomplete run directory")] = None,
    cache: Annotated[Path, typer.Option(help="Verified upstream dataset cache")] = Path(
        ".cache/cheapgpt-benchmarks"
    ),
    concurrency: Annotated[int, typer.Option(min=1, max=32)] = 4,
    max_rpm: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum HTTP requests per rolling minute, including retries"),
    ] = 100,
    timeout: Annotated[float, typer.Option(min=1)] = DEFAULT_TIMEOUT_SECONDS,
    max_cost_usd: Annotated[
        float | None,
        typer.Option(min=0.01, help="Stop scheduling requests at this observed provider cost"),
    ] = None,
) -> None:
    """Run a normalized request plan and retain every transport attempt."""
    api_key = os.getenv("CHEAPGPT_API_KEY")
    if not api_key:
        raise typer.BadParameter("CHEAPGPT_API_KEY is required")
    profile_config = load_profile(repository_file(f"profiles/{profile}.yaml"))
    selected_effort = effort or default_effort(model)
    scoring_key: dict[str, str] | None = None
    arc_scoring_key: dict[str, dict[str, object]] | None = None
    quick_expected = None
    benchmark_contract = None
    dataset_sha256 = None
    if plan is None:
        if profile == "quick":
            selected_benchmarks: list[str] = (
                [benchmark] if benchmark else profile_config.benchmarks
            )
            quick_assets = load_quick_assets(
                repository_file("quick"), selected_benchmarks, cache
            )
            items = quick_assets.plan
            quick_expected = quick_assets.expected
        elif track == "leaderboard" and benchmark == "gpqa-diamond":
            gpqa_contract = prepare_gpqa(cache)
            items = gpqa_contract.plan
            scoring_key = gpqa_contract.expected
            benchmark_contract = gpqa_contract.id
            dataset_sha256 = gpqa_contract.dataset_sha256
        elif track == "leaderboard" and benchmark == "arc-agi-2":
            arc_contract = prepare_arc_agi_2(cache)
            items = arc_contract.plan
            arc_scoring_key = arc_contract.expected
            benchmark_contract = arc_contract.id
            dataset_sha256 = arc_contract.dataset_sha256
        else:
            default_plan = Path(".benchmarks") / "plans" / f"{profile_config.id}.jsonl"
            if not default_plan.exists():
                raise typer.BadParameter(
                    "This adapter is not released yet. Use --profile full --track leaderboard "
                    "with --benchmark gpqa-diamond or --benchmark arc-agi-2, or pass a "
                    "development --plan."
                )
            items = load_plan(default_plan)
    else:
        items = load_plan(plan)
    if benchmark is not None:
        items = [item for item in items if item.benchmark == benchmark]
        if not items:
            raise typer.BadParameter(
                f"No {benchmark} items exist in the selected request plan"
            )
    items = [
        item.model_copy(
            update={
                "parameters": {
                    **item.parameters,
                    "reasoning": {"effort": selected_effort},
                }
            }
        )
        for item in items
    ]
    manifest, run_root = asyncio.run(
        run_plan(
            api_key=api_key,
            base_url=os.getenv("CHEAPGPT_BASE_URL", DEFAULT_BASE_URL),
            timeout=timeout,
            model=model,
            profile=profile_config.id,
            track=track,
            attempts_per_item=profile_config.attempts_per_item,
            plan=items,
            output_root=output,
            benchmark_lock=repository_file("benchmarks.lock.yaml"),
            concurrency=concurrency,
            max_rpm=max_rpm,
            reasoning_effort=selected_effort,
            resume_root=resume,
            scoring_key=scoring_key,
            arc_scoring_key=arc_scoring_key,
            quick_expected=quick_expected,
            quick_expected_root=(repository_file("quick/expected") if profile == "quick" else None),
            docker_context=(repository_file("docker") if profile == "quick" else None),
            benchmark_contract=benchmark_contract,
            dataset_sha256=dataset_sha256,
            max_cost_usd=max_cost_usd,
        )
    )
    color = "green" if manifest.status == "completed" else "yellow"
    console.print(f"[{color}]{manifest.status}[/{color}] · {manifest.run_id}")
    console.print(f"JSONL: {run_root / 'attempts.jsonl'}")
    console.print(f"HTML:  {run_root / 'report.html'}")
    score_path = run_root / "score-summary.json"
    if score_path.exists():
        score = json.loads(score_path.read_text(encoding="utf-8"))
        if "benchmarks" in score:
            for name, result in score["benchmarks"].items():
                detail = (
                    f"attempt accuracy {result['attempt_accuracy']}%"
                    if "attempt_accuracy" in result
                    else f"{result['scored_attempts']} attempts scored"
                )
                console.print(f"{name}: [bold]{result['score']}%[/bold] · {detail}")
        else:
            detail = ""
            if "confidence_interval_95" in score:
                detail = (
                    f" · 95% CI {score['confidence_interval_95'][0]}-"
                    f"{score['confidence_interval_95'][1]}%"
                )
            console.print(f"Score: [bold]{score['score']}%[/bold]{detail}")


@app.command()
def verify(run_directory: Path) -> None:
    """Verify hashes and counts in a local run directory."""
    from cheapgpt_benchmarks.verify import verify_run

    result = verify_run(run_directory)
    console.print(
        f"[green]verified[/green] · {result['attempt_count']} transport attempts · "
        f"{result['logical_attempt_count']} logical attempts"
    )


@app.command()
def bundle(
    run_directory: Path,
    author: Annotated[str, typer.Option(help="GitHub username or organization")],
    output: Annotated[Path, typer.Option()] = Path("community-bundle"),
) -> None:
    """Create an explicit, non-official community PR bundle."""
    from cheapgpt_benchmarks.verify import verify_run

    verify_run(run_directory)
    bundle_root = create_bundle(run_directory, output, author)
    console.print(f"[green]community bundle ready[/green] · {bundle_root}")


@app.command("verify-bundle")
def verify_community_bundle(bundle_directory: Path) -> None:
    """Verify a community PR bundle and its immutable non-official marker."""
    metadata = verify_bundle(bundle_directory)
    console.print(f"[green]community bundle verified[/green] · {metadata['submission_id']}")


@app.command("prepare-release")
def prepare_official_release(
    run_directories: list[Path],
    signing_key: Annotated[
        Path, typer.Option(help="Minisign secret key stored outside the repository")
    ],
    output: Annotated[Path, typer.Option(help="New draft directory named YYYY-MM-DD.N")],
) -> None:
    """Package completed runs into a signed official release draft."""
    release = prepare_release(run_directories, output, signing_key)
    console.print(
        f"[green]official release ready[/green] · {release['release_id']} · "
        f"{len(release['runs'])} runs"
    )


@app.command("verify-release")
def verify_official_release(
    release_directory: Path,
    public_key: Annotated[Path, typer.Option(help="Trusted Minisign public key")],
) -> None:
    """Verify the signature, hashes and deterministic scores of a release."""
    release = verify_release(release_directory, public_key)
    console.print(
        f"[green]official release verified[/green] · {release['release_id']} · "
        f"{len(release['runs'])} runs"
    )


@app.command("index-release")
def index_official_release(
    release_directory: Path,
    public_key: Annotated[Path, typer.Option(help="Trusted Minisign public key")],
    release_url: Annotated[str, typer.Option(help="Public GitHub Release URL")],
    reference_matrix: Annotated[Path, typer.Option()] = Path("references/matrix.yaml"),
    official_index: Annotated[Path, typer.Option()] = Path("official/index.json"),
    leaderboard_index: Annotated[Path, typer.Option()] = Path("leaderboard/index.json"),
) -> None:
    """Add a verified result release to the public machine-readable indexes."""
    rows = index_release(
        release_directory,
        public_key,
        reference_matrix,
        official_index,
        leaderboard_index,
        release_url,
    )
    console.print(f"[green]official indexes updated[/green] · {len(rows)} comparable rows")


if __name__ == "__main__":
    app()
