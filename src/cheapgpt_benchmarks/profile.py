from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    id: str
    attempts_per_item: int
    selection: str
    benchmarks: list[str]
    status: str


def load_profile(path: Path) -> Profile:
    return Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
