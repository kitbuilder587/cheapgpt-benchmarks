from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    benchmark: str
    prompt: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    attempts: int | None = Field(default=None, ge=1)


def load_plan(path: Path) -> list[PlanItem]:
    items: list[PlanItem] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                items.append(PlanItem.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"Invalid plan item at line {line_number}: {exc}") from exc
    if not items:
        raise ValueError("Plan is empty")
    return items
