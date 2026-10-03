import html
import json
from pathlib import Path

from cheapgpt_benchmarks.models import AttemptRecord, RunManifest


def write_html(root: Path, manifest: RunManifest, attempts: list[AttemptRecord]) -> None:
    completed = sum(record.status == "completed" for record in attempts)
    input_tokens = sum(record.usage.input_tokens or 0 for record in attempts if record.usage)
    output_tokens = sum(record.usage.output_tokens or 0 for record in attempts if record.usage)
    score_path = root / "score-summary.json"
    score = json.loads(score_path.read_text(encoding="utf-8")) if score_path.exists() else None
    if score and "benchmarks" in score:
        score_value = f"{score['scored_benchmarks']}/{score['expected_benchmarks']} scored"
    else:
        score_value = f"{score['score']}%" if score and score.get("score") is not None else "—"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(record.benchmark)}</td>"
        f"<td>{html.escape(record.item_id)}</td>"
        f"<td>{record.attempt}</td>"
        f"<td>{html.escape(record.status)}</td>"
        f"<td>{record.latency_ms:,}</td>"
        f"<td>{(record.usage.total_tokens if record.usage else None) or '—'}</td>"
        "</tr>"
        for record in attempts
    )
    manifest_json = html.escape(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    document = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(manifest.run_id)} · CheapGPT Benchmarks</title>
<style>
:root {{ color-scheme: dark; font-family: ui-monospace, SFMono-Regular, monospace; }}
body {{ margin: 0; background: #10110f; color: #ecebdc; }}
main {{ max-width: 1080px; margin: auto; padding: 4rem 1.25rem; }}
.eyebrow {{ color: #c7ff44; text-transform: uppercase; letter-spacing: .12em; }}
h1 {{ font: 700 clamp(2rem, 7vw, 5rem)/.95 Georgia, serif; max-width: 12ch; }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: #3b3d37; border: 1px solid #3b3d37; }}
.metric {{ background: #181a17; padding: 1.25rem; }} .metric strong {{ display:block; font-size:2rem; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 3rem; }}
th,td {{ padding: .75rem; border-bottom: 1px solid #3b3d37; text-align:left; }}
pre {{ overflow:auto; background:#181a17; padding:1rem; }}
@media (max-width: 650px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
<main>
<p class="eyebrow">Local run dossier</p><h1>{html.escape(manifest.model)}</h1>
<p>{html.escape(manifest.profile)} · {html.escape(manifest.track)} · {html.escape(manifest.run_id)}</p>
<section class="grid">
<div class="metric"><span>Completed</span><strong>{completed}/{len(attempts)}</strong></div>
<div class="metric"><span>Input tokens</span><strong>{input_tokens:,}</strong></div>
<div class="metric"><span>Output tokens</span><strong>{output_tokens:,}</strong></div>
<div class="metric"><span>Score</span><strong>{score_value}</strong></div>
</section>
<table><thead><tr><th>Benchmark</th><th>Item</th><th>Attempt</th><th>Status</th><th>ms</th><th>Tokens</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Manifest</h2><pre>{manifest_json}</pre>
</main></html>"""
    (root / "report.html").write_text(document, encoding="utf-8")
