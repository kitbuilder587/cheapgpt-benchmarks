# Latest ARC-AGI-2 run

Run `2026-09-04.3` completed on 2026-09-05 through
`https://api.aiproductiv.ru/v1/responses` (CheapGPT), requesting `gpt-5.6-sol` with
reasoning effort `medium`.

| Metric | Result |
| --- | ---: |
| Two-attempt task accuracy | 67.778% |
| Evaluation tasks | 120 |
| Test pairs | 167 |
| Scored logical attempts | 334 / 334 |
| Fully solved tasks | 75 |
| Partially solved tasks | 13 |
| Unsolved tasks | 32 |

A test pair passes if either logical attempt exactly matches its expected grid. Each task's
score is the fraction of its test pairs that pass; the final percentage averages over all
120 tasks. This is not the percentage of individual correct attempts or fully solved tasks.

## Dataset and request

The dataset is the complete public evaluation split at ARC-AGI-2 revision
`f3283f727488ad98fe575ea6a5ac981e4a188e49`, pinned in `benchmarks.lock.yaml`.
Archive SHA-256: `179681bc01d55810ee0e90d2717ef04b8d130496541c4853479a8d6fffa4b975`.
The contract is `arc-prize-arc-agi-2-public-eval-text-v1`.

Each request contains all training examples and one test input as textual integer grids.
The requested parameters were `max_output_tokens=128000`, `store=false` and
`reasoning.effort=medium`. Concurrency was 4, with a 100 RPM limit and an HTTP client
timeout of 1800 seconds. The client supplied no tools or conversation history.
The API route may transform the request: streaming response metadata reports the instructions
`You are a helpful assistant.` followed by a request to keep the output within approximately
128000 tokens. The requested output limit is not evidence of an identical enforced upstream cap.

## Transport and retries

| Transport | Successful responses | HTTP errors |
| --- | ---: | ---: |
| Non-streaming | 118 | 35 |
| Streaming | 217 | 0 |
| Total | 335 | 35 |

The run was resumed after non-streaming calls encountered HTTP 504 responses at approximately
300 seconds. The remaining calls used `stream=true`; prompts and reasoning effort were unchanged.
The client preserves the terminal response object, including output and usage. Fourteen
streaming responses took longer than 300 seconds; the longest took 467.170 seconds.
This is a completed run with mixed transport, not a fresh all-streaming experiment.

HTTP retries remain attached to the same logical attempt. For an ARC output that cannot be
parsed, the runner permits another generation for that logical attempt. One such regeneration
occurred here, giving 335 successful responses for 334 logical attempts. The last successful
response for each logical attempt is scored. This format-retry policy is part of this harness
and must be accounted for when comparing with other implementations.
All failed and repeated transport records are retained; no failed tasks were dropped.

## Usage

| Token category | Tokens |
| --- | ---: |
| Input | 2,423,732 |
| Output, including reasoning | 1,826,354 |
| Reasoning, already included in output | 1,405,504 |
| Input + output | 4,250,086 |

Usage totals include all 335 successful responses, including the format retry. The 35 HTTP
errors did not return usage, so these counts do not establish total provider billing.

## Artifacts and verification

[`results/index.json`](../results/index.json) contains the result derived from the source
manifest, summary and attempts, with SHA-256 hashes for the six artifacts in
[`results/2026-09-04.3/`](../results/2026-09-04.3/).
Provider-issued identifiers and encrypted reasoning payloads were redacted with the current
sanitizer and each record hash was recomputed; output text, usage and every score are unchanged.
The full JSONL is deterministically gzip-compressed; decompressing restores the original
sanitized attempt records and their content hashes.

```bash
uv run python scripts/export_result.py --check
```

This checks the exact public file set, hashes, completeness, every saved score and the public
index against a fresh deterministic rescore. CI runs the same check without API credentials.
Only this explicitly selected run is distributed; local diagnostic directories are not inputs
to the site or the public result exporter.

This result is **unsigned** and has not passed the separate signed official-release workflow.
It is therefore displayed separately from `official/index.json` and the signed leaderboard.
It measures observed capability through CheapGPT. The returned model name is normalized by
the provider and does not independently attest to the upstream model or account.
