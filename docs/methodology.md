# Methodology

## Claim boundary

The project measures observable model capability. It can expose a material quality gap between
a claimed flagship and a smaller control model, but it cannot identify provider weights with
cryptographic certainty. The provider may normalize the returned model name to the requested
name, so this field alone does not establish upstream identity.

## Profiles

`quick-v1` is a fixed, versioned subset of LiveBench, HLE text-only, GPQA Diamond, MMLU-Pro and
LiveCodeBench. Every item is attempted three times. The target runtime is ten minutes on a normal
developer connection; the item set never changes in response to cost or model output.
GPQA Diamond and HLE quick prompts are rebuilt at run time from their upstream sources and must
match the pinned plan hashes; their plain text is never bundled.
Multiple-choice results use majority accuracy across the three attempts. LiveBench and
LiveCodeBench use their pinned upstream scorers inside a network-disabled Docker sandbox.

`full-v1` uses a selected benchmark's pinned full contract. ARC-AGI-2 uses all 120 public
evaluation tasks, 167 test pairs and two logical attempts per pair. GPQA Diamond uses 198
questions and five deterministic permutations per question. The contracts determine repetition
and scoring; full-run results must not be inferred from the quick profile.

## Tracks

`default` sends the same benchmark inputs using CheapGPT defaults. `leaderboard` uses the exact
generation parameters required for a comparable official leaderboard run. Track results never mix.

## Comparability

A result is compared with an external score only when benchmark release, dataset snapshot,
scoring configuration and reasoning effort match. Otherwise it remains public and is labeled
`Not comparable`. Operator-run controls through other routes must identify the route and are
not independent third-party evaluations merely because the provider differs.

## Reproducibility

Official upstream repositories and revisions are pinned in `benchmarks.lock.yaml`. Official
harnesses own prompt construction and scoring. The CheapGPT runner orchestrates them, records API
traffic, normalizes provenance and verifies that rescoring the saved responses is deterministic.

Each client execution permits at most two retries of retryable transport failures, waiting
10 and 30 seconds. A failed execution stops the run; explicit resumption may retry it again.
ARC outputs that cannot be parsed permit a second generation for the same logical attempt.
The scorer selects the last successful response for each logical attempt. This format retry
can consume more generations than the nominal attempt count and must be disclosed.

Requests use Responses streaming; output and usage come from the terminal response object.
All transport attempts are retained, and a run with unresolved logical attempts stays
`incomplete`. See [latest-run.md](latest-run.md) for the completed run's mixed transport history.
