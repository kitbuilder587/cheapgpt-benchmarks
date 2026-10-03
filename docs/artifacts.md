# Artifact contract

Each run directory contains:

- `manifest.json`: run identity, versions, model, track, state and counts;
- `attempts.jsonl`: immutable request/response records, including failed and retried calls;
- `report.html`: standalone local summary;
- scorer outputs emitted by each pinned official harness.

The JSON Schemas in `schemas/` are normative. A transport attempt hash covers its sanitized
request, response and error. Official full-run JSONL is compressed, checksummed with SHA-256 and
signed with Minisign in a GitHub Release. Code versions use SemVer; result IDs use `YYYY-MM-DD.N`.

`results/index.json` explicitly selects the latest unsigned, deterministically rescored result
and lists its artifact hashes. The site reads this index, never local `runs/` directories.
`uv run python scripts/export_result.py --check` verifies the exact public artifact set.

The `official/index.json` file is the only machine-readable source for the latest signed official
run. Unsigned results do not populate it or the signed leaderboard. GitHub Pages must not infer
“latest” from filenames or release dates.
