# Community submissions

The local runner does not upload data or collect telemetry. A contributor may explicitly create a
submission bundle and open a pull request. CI validates its schemas, hashes, benchmark pins and
deterministic rescoring.

```bash
uvx cheapgpt-benchmarks bundle runs/2026-09-03.1 --author @your-github-name
```

Commit the resulting directory under `community/submissions/<submission-id>/`. The bundle records
the author, run configuration and SHA-256 of every included artifact. Creation is always explicit;
the `run` command never uploads or submits results.

Community runs appear in a separate section and can never set `official: true`, update
`latest_verified_run`, use CheapGPT release signatures or be presented as maintainer runs.
