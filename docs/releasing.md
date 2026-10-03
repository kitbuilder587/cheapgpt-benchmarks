# Releasing

## Checked result snapshots

The latest completed ARC-AGI-2 run is distributed as an unsigned snapshot in `results/`.
Its explicit `results/index.json` selection drives the website; the official indexes below
remain separate. To prepare an explicitly selected local run:

```bash
uv run python scripts/export_result.py runs/2026-09-04.3
uv run python scripts/export_result.py --check
```

Export refuses to overwrite an existing run directory. Use `--check` for an already exported
snapshot. The check verifies the exact public file set, compressed artifact hashes and scores;
CI and the Pages workflow both require it. The exporter never scans or uploads local `runs/`
directories and does not create a GitHub Release or signature.

## Runner

Code releases use SemVer tags. GitHub trusted publishing sends `v*` releases to PyPI. Before the
first stable release, configure the `pypi` environment and its trusted publisher for this
repository.

## Official results

Official result IDs use `YYYY-MM-DD.N`; the Git tag and release directory must use that exact ID.
Only completed, deterministically verified runs may be packaged:

```bash
uv run cheapgpt-benchmarks prepare-release \
  runs/sol runs/terra runs/luna runs/gpt-5.5 \
  --output dist/2026-09-03.1 \
  --signing-key /secure/offline/cheapgpt-benchmarks.key
```

The command verifies every run, compresses full request/response JSONL deterministically, includes
the manifest, scoring key, scores, summary and HTML report, writes SHA-256 checksums and signs the
checksum manifest with Minisign.

Create a draft GitHub Release with the same tag, upload every file from the output directory, then
run the `Verify official result release` workflow with that tag. The workflow downloads the draft,
checks the committed public key, signature, exact artifact set and hashes, and deterministically
rescores every run. Publish only after the workflow succeeds and one maintainer approves it.

Anyone can perform the same verification locally:

```bash
uvx cheapgpt-benchmarks verify-release 2026-09-03.1 \
  --public-key keys/official.minisign.pub
```

After publishing the verified GitHub Release, update both public indexes from the signed data:

```bash
uv run cheapgpt-benchmarks index-release dist/2026-09-03.1 \
  --public-key keys/official.minisign.pub \
  --release-url https://github.com/kitbuilder587/cheapgpt-benchmarks/releases/tag/2026-09-03.1
```

The command rejects runs not marked `run` in the reference matrix and derives scores, reference
values, provenance and artifact links without manually copying benchmark numbers.

## Signing key

Provision the Minisign key during a manual security ceremony. Keep the encrypted secret key and
its passphrase outside GitHub; commit only `keys/official.minisign.pub`. Official publication stays
disabled until that public key exists. Rotate by committing a new public key before creating a
release, and retain retired public keys wherever their historical releases remain available.
