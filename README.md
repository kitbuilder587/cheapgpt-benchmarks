# CheapGPT Benchmarks

Public, reproducible evidence for the observed quality of models served by CheapGPT.

> [!IMPORTANT]
> The latest published dataset is a complete ARC-AGI-2 run: **67.778%** for
> `gpt-5.6-sol`, reasoning `medium`, through CheapGPT. All 334 logical attempts pass
> deterministic verification. The artifacts are checksummed but not signed as an official release.

Benchmark results measure the capability observed through the declared route. The returned
model name is provider-controlled and may be normalized to the requested name; it does not
independently establish the identity of the upstream model.

## Latest result

| Run | Benchmark | Model / reasoning | Score | Coverage |
| --- | --- | --- | ---: | --- |
| 2026-09-04.3 | ARC-AGI-2 public evaluation | gpt-5.6-sol / medium | **67.778%** | 120 tasks, 167 test pairs, 334 attempts |

Completed on September 5, 2026. 75 tasks are fully solved, 13 partially solved.
The run contains 370 transport records: 335 successful responses and 35 HTTP errors, all
followed by successful retries. One logical attempt received an extra response after a parse
failure. The run resumed with streaming after 300-second non-streaming timeouts:
118 successful responses use non-streaming and 217 use streaming, with zero streaming errors.

[Run notes](docs/latest-run.md) · [Machine-readable result and SHA-256 hashes](results/index.json) ·
[HTML report](results/2026-09-04.3/report.html) ·
[Full request/response log](results/2026-09-04.3/attempts.jsonl.gz)

Verify the committed result without making API calls:

```bash
uv run python scripts/export_result.py --check
```

Only the explicitly selected run is included in `results/`. Local `runs/` directories are ignored.
`official/index.json` remains reserved for signed releases.

## Run the public quick profile

```bash
CHEAPGPT_API_KEY=... HF_TOKEN=... uvx cheapgpt-benchmarks run --model gpt-5.5
```

The default `quick-v1` profile runs 26 fixed items from all five benchmarks three times each.
GPQA Diamond and HLE prompts are not redistributed: GPQA items are rebuilt from the public
OpenAI simple-evals CSV, and HLE items are fetched from the gated `cais/hle` dataset, which
requires accepting its terms on Hugging Face and an `HF_TOKEN`. Every plan, bundled or rebuilt,
must match its pinned SHA-256. The runner retains all API attempts and produces terminal, HTML and
JSONL results. LiveBench and LiveCodeBench scoring runs inside a network-disabled Docker sandbox;
the pinned scorer image is pulled from GHCR, with a reproducible local build as fallback.

Comparable full contracts are also runnable. GPQA Diamond uses the Artificial Analysis contract:

```bash
CHEAPGPT_API_KEY=... uv run cheapgpt-benchmarks run \
  --model gpt-5.6-sol \
  --profile full \
  --track leaderboard \
  --benchmark gpqa-diamond
```

The runner downloads the public GPQA Diamond CSV, verifies its SHA-256, generates the published
Artificial Analysis prompt with five deterministic permutations per question, fixes the model's
reasoning effort explicitly and caps all traffic at 100 RPM by default. `--resume RUN_DIRECTORY`
continues only missing logical attempts. The completed directory contains the full request and
response JSONL, deterministic scores with a 95% interval and a local HTML report.

ARC-AGI-2 uses the ARC Prize public-evaluation contract:

```bash
CHEAPGPT_API_KEY=... uv run cheapgpt-benchmarks run \
  --model gpt-5.6-sol \
  --profile full \
  --track leaderboard \
  --benchmark arc-agi-2 \
  --effort medium \
  --concurrency 4 \
  --max-rpm 100 \
  --timeout 1800
```

This downloads the 120 public evaluation tasks at a pinned commit and checksum, generates the
ARC Prize text prompt for all 167 test grids and makes two logical attempts per grid. Scoring is
the per-task average, with either attempt allowed to solve a test grid. Requests now use
Responses streaming and save the terminal response object. See the [run notes](docs/latest-run.md)
for the exact retry policy and the mixed transport history of the committed result.

## Benchmark matrix

| Benchmark | Variant | Upstream |
| --- | --- | --- |
| ARC-AGI-2 | public evaluation, text | [ARC Prize](https://github.com/arcprize/ARC-AGI-2) |
| LiveBench | pinned release | [LiveBench](https://github.com/LiveBench/LiveBench) |
| Humanity's Last Exam | text-only | [HLE](https://github.com/centerforaisafety/hle) |
| GPQA | Diamond | [GPQA](https://github.com/idavidrein/gpqa) |
| MMLU-Pro | complete | [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro) |
| LiveCodeBench | complete | [LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench) |

Every model receives the same dataset, scorer and benchmark configuration. V1 models:

- `gpt-5.6-sol` (`low` by default)
- `gpt-5.6-terra` (`medium` by default)
- `gpt-5.6-luna` (`medium` by default)
- `gpt-5.5` (`medium` by default)

The pre-run [reference matrix](docs/reference-matrix.md) records independent results for every
published effort and gates expensive official runs. The first eligible comparison contract is
Artificial Analysis GPQA Diamond: 198 questions, five repeats, matching effort and published
prompt/scoring rules.

## What is recorded

Each transport attempt records the complete benchmark request and all API content returned
to the runner, including final text, tool calls, citations and available reasoning summaries.
It also records requested and returned model names, run/item IDs, timestamps, latency,
usage, errors, retries and a canonical SHA-256.

Authorization headers, API keys, cookies, PII, internal account/route IDs, internal URLs and
unrelated user traffic are never publication artifacts. Provider-issued identifiers that could
link a run to an upstream account (response, message, reasoning and request IDs, safety and
prompt-cache identifiers, turn metadata) and encrypted reasoning payloads are redacted before
the record is hashed. The runner has no telemetry and does
not upload local results.

## Development

```bash
uv sync --all-extras --dev
uv run cheapgpt-benchmarks doctor
uv run pytest
uv run ruff check .
uv run mypy
```

Adapter developers may pass a validated JSONL request plan with `--plan`. This low-level path
exists for harness integration; its output must not be represented as an official result.

See [methodology](docs/methodology.md), [artifact contract](docs/artifacts.md),
[security](docs/security.md), [community submissions](docs/community.md),
[leaderboard contract](docs/leaderboard.md), [official release procedure](docs/releasing.md), and
[canary protocol](docs/canaries.md). The
machine-readable comparison decisions are in
[`references/matrix.yaml`](references/matrix.yaml).

Licensed under Apache-2.0.
