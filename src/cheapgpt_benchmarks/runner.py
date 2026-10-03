import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cheapgpt_benchmarks import __version__
from cheapgpt_benchmarks.artifacts import ArtifactWriter
from cheapgpt_benchmarks.client import BenchmarkRequest, ResponsesClient
from cheapgpt_benchmarks.hashing import file_sha256
from cheapgpt_benchmarks.models import AttemptRecord, RunManifest
from cheapgpt_benchmarks.plan import PlanItem
from cheapgpt_benchmarks.report import write_html
from cheapgpt_benchmarks.scoring import extract_arc_grid, output_text


def next_run_id(root: Path, now: datetime | None = None) -> str:
    date = (now or datetime.now(UTC)).date().isoformat()
    sequence = 1
    while (root / f"{date}.{sequence}").exists():
        sequence += 1
    return f"{date}.{sequence}"


async def run_plan(
    *,
    api_key: str,
    base_url: str,
    timeout: float,
    model: str,
    profile: str,
    track: Literal["default", "leaderboard"],
    attempts_per_item: int,
    plan: list[PlanItem],
    output_root: Path,
    benchmark_lock: Path,
    concurrency: int,
    max_rpm: int | None = None,
    reasoning_effort: str | None = None,
    resume_root: Path | None = None,
    scoring_key: dict[str, str] | None = None,
    arc_scoring_key: dict[str, dict[str, object]] | None = None,
    quick_expected: dict[str, dict[str, dict[str, object]]] | None = None,
    quick_expected_root: Path | None = None,
    docker_context: Path | None = None,
    benchmark_contract: str | None = None,
    dataset_sha256: str | None = None,
    max_cost_usd: float | None = None,
) -> tuple[RunManifest, Path]:
    benchmark_lock_sha256 = file_sha256(benchmark_lock)
    expected = sum(item.attempts or attempts_per_item for item in plan)
    started_at = datetime.now(UTC)
    run_root = resume_root or output_root / next_run_id(output_root, started_at)
    writer = ArtifactWriter(run_root)
    existing_records = writer.read_attempts()
    if resume_root:
        manifest = RunManifest.model_validate_json(writer.manifest_path.read_text())
        actual = (
            manifest.model,
            manifest.profile,
            manifest.track,
            manifest.reasoning_effort,
            manifest.benchmark_contract,
            manifest.dataset_sha256,
        )
        requested = (
            model,
            profile,
            track,
            reasoning_effort,
            benchmark_contract,
            dataset_sha256,
        )
        if actual != requested or manifest.benchmark_lock_sha256 != benchmark_lock_sha256:
            raise ValueError("Resume run configuration does not match the requested run")
        manifest = manifest.model_copy(update={"finished_at": None, "status": "running"})
    else:
        manifest = RunManifest(
            run_id=run_root.name,
            cli_version=__version__,
            profile=profile,
            track=track,
            model=model,
            reasoning_effort=reasoning_effort,
            benchmark_contract=benchmark_contract,
            dataset_sha256=dataset_sha256,
            started_at=started_at,
            status="running",
            benchmark_lock_sha256=benchmark_lock_sha256,
            attempt_count=0,
            completed_count=0,
            error_count=0,
            expected_logical_attempt_count=expected,
            completed_logical_attempt_count=0,
        )
    writer.write_manifest(manifest)
    client = ResponsesClient(api_key, base_url, timeout, max_rpm)
    completed_records: dict[tuple[str, int], list[AttemptRecord]] = {}
    for record in existing_records:
        if record.status == "completed":
            completed_records.setdefault((record.item_id, record.attempt), []).append(record)
    completed_logical_attempts: set[tuple[str, int]] = set()
    for key, records in completed_records.items():
        if records[-1].benchmark != "arc-agi-2":
            completed_logical_attempts.add(key)
        elif any(extract_arc_grid(output_text(record.response.body)) for record in records):
            completed_logical_attempts.add(key)
        elif len(records) >= 2:
            completed_logical_attempts.add(key)
    jobs = iter(
        (item, attempt_number)
        for item in plan
        for attempt_number in range(1, (item.attempts or attempts_per_item) + 1)
        if (item.id, attempt_number) not in completed_logical_attempts
    )
    pending = expected - len(completed_logical_attempts)
    attempt_count = len(existing_records)
    completed_count = sum(record.status == "completed" for record in existing_records)
    error_count = sum(record.status == "error" for record in existing_records)
    successful_logical_attempts = len(completed_logical_attempts)
    observed_cost_usd = 0.0
    for record in existing_records:
        if record.usage is None or not isinstance(record.usage.details, dict):
            continue
        cost = record.usage.details.get("cost")
        if isinstance(cost, int | float):
            observed_cost_usd += float(cost)
    cost_lock = asyncio.Lock()

    async def account_cost(records: list[AttemptRecord]) -> None:
        nonlocal observed_cost_usd
        if max_cost_usd is None:
            return
        costs: list[float] = []
        for record in records:
            if record.status != "completed":
                continue
            cost = record.usage.details.get("cost") if record.usage else None
            if not isinstance(cost, int | float):
                raise RuntimeError("Provider did not return usage.cost; budget cannot be enforced")
            costs.append(float(cost))
        async with cost_lock:
            observed_cost_usd += sum(costs)
            if observed_cost_usd >= max_cost_usd:
                raise RuntimeError(
                    f"Observed provider cost ${observed_cost_usd:.4f} reached "
                    f"the ${max_cost_usd:.2f} stop"
                )

    async def execute_job(item: PlanItem, attempt_number: int) -> None:
        nonlocal attempt_count, completed_count, error_count, successful_logical_attempts
        parse_attempts = 2 if item.benchmark == "arc-agi-2" else 1
        for parse_attempt in range(parse_attempts):
            records = await client.execute(
                BenchmarkRequest(
                    run_id=manifest.run_id,
                    item_id=item.id,
                    benchmark=item.benchmark,
                    attempt=attempt_number,
                    track=track,
                    model=model,
                    prompt=item.prompt,
                    parameters=item.parameters,
                )
            )
            for record in records:
                writer.append_attempt(record)
            attempt_count += len(records)
            completed_count += sum(record.status == "completed" for record in records)
            error_count += sum(record.status == "error" for record in records)
            await account_cost(records)
            final_record = records[-1]
            if final_record.status == "error" and not final_record.retryable:
                status_code = final_record.response.status_code
                raise RuntimeError(f"Non-retryable API error ({status_code})")
            if final_record.status == "error":
                raise RuntimeError("API request still failed after two retries")
            if final_record.returned_model != model:
                raise RuntimeError(
                    f"Returned model {final_record.returned_model!r} does not match {model!r}"
                )
            if extract_arc_grid(output_text(final_record.response.body)) is not None:
                break
            if parse_attempt == parse_attempts - 1:
                break
        successful_logical_attempts += 1

    async def worker() -> None:
        nonlocal attempt_count, completed_count, error_count, successful_logical_attempts
        while True:
            try:
                item, attempt_number = next(jobs)
            except StopIteration:
                return
            await execute_job(item, attempt_number)
            if successful_logical_attempts % 100 == 0:
                writer.write_manifest(
                    manifest.model_copy(
                        update={
                            "attempt_count": attempt_count,
                            "completed_count": completed_count,
                            "error_count": error_count,
                            "expected_logical_attempt_count": expected,
                            "completed_logical_attempt_count": successful_logical_attempts,
                        }
                    )
                )

    workers: list[asyncio.Task[None]] = []
    try:
        if not completed_logical_attempts and pending:
            first_item, first_attempt = next(jobs)
            await execute_job(first_item, first_attempt)
            pending -= 1
        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, pending))]
        await asyncio.gather(*workers)
    except Exception:
        for worker_task in workers:
            worker_task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        writer.write_manifest(
            manifest.model_copy(
                update={
                    "finished_at": datetime.now(UTC),
                    "status": "incomplete",
                    "attempt_count": attempt_count,
                    "completed_count": completed_count,
                    "error_count": error_count,
                    "expected_logical_attempt_count": expected,
                    "completed_logical_attempt_count": successful_logical_attempts,
                }
            )
        )
        raise
    finally:
        await client.close()

    manifest = manifest.model_copy(
        update={
            "finished_at": datetime.now(UTC),
            "status": "completed" if successful_logical_attempts == expected else "incomplete",
            "attempt_count": attempt_count,
            "completed_count": completed_count,
            "error_count": error_count,
            "expected_logical_attempt_count": expected,
            "completed_logical_attempt_count": successful_logical_attempts,
        }
    )
    writer.write_manifest(manifest)
    records = writer.read_attempts()
    if scoring_key is not None:
        from cheapgpt_benchmarks.scoring import write_gpqa_scores

        write_gpqa_scores(run_root, records, scoring_key)
    elif arc_scoring_key is not None:
        from cheapgpt_benchmarks.scoring import write_arc_agi_2_scores

        write_arc_agi_2_scores(run_root, records, arc_scoring_key)
    elif quick_expected is not None:
        from cheapgpt_benchmarks.scoring import write_quick_choice_scores

        write_quick_choice_scores(run_root, records, quick_expected)
        if quick_expected_root is not None and docker_context is not None:
            from cheapgpt_benchmarks.sandbox import score_quick_sandboxed

            score_quick_sandboxed(run_root, quick_expected_root, docker_context)
    write_html(run_root, manifest, records)
    return manifest, run_root
