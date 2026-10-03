import os
from typing import Any

import httpx

from cheapgpt_benchmarks.plan import PlanItem

ROWS_URL = "https://datasets-server.huggingface.co/filter"


def _rows(dataset: str, ids: list[str], token: str) -> dict[str, dict[str, Any]]:
    where = " OR ".join(f"\"id\"='{item_id}'" for item_id in ids)
    response = httpx.get(
        ROWS_URL,
        params={"dataset": dataset, "config": "default", "split": "test", "where": where},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()
    return {row["row"]["id"]: row["row"] for row in response.json()["rows"]}


def build_hle_quick_plan(source: dict[str, Any]) -> list[PlanItem]:
    token = os.getenv("HF_TOKEN")
    if not token:
        raise ValueError(
            "HLE quick items are fetched from the gated cais/hle dataset at run time: "
            "accept its terms on Hugging Face and set HF_TOKEN"
        )
    rows = _rows(source["dataset"], source["items"], token)
    missing = set(source["items"]).difference(rows)
    if missing:
        raise ValueError(f"HLE rows not found: {', '.join(sorted(missing))}")
    return [
        PlanItem(
            id=f"hle-{item_id}",
            benchmark="hle",
            prompt=rows[item_id]["question"],
            parameters=source["parameters"],
        )
        for item_id in source["items"]
    ]
