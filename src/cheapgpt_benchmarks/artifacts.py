import json
from pathlib import Path

from cheapgpt_benchmarks.hashing import canonical_json
from cheapgpt_benchmarks.models import AttemptRecord, RunManifest


class ArtifactWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.attempts_path = root / "attempts.jsonl"
        self.manifest_path = root / "manifest.json"

    def append_attempt(self, attempt: AttemptRecord) -> None:
        with self.attempts_path.open("ab") as destination:
            destination.write(canonical_json(attempt.model_dump(mode="json")) + b"\n")

    def read_attempts(self) -> list[AttemptRecord]:
        if not self.attempts_path.exists():
            return []
        return [
            AttemptRecord.model_validate_json(line)
            for line in self.attempts_path.read_text(encoding="utf-8").split("\n")
            if line
        ]

    def write_manifest(self, manifest: RunManifest) -> None:
        payload = json.dumps(
            manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        )
        self.manifest_path.write_text(payload + "\n", encoding="utf-8")
