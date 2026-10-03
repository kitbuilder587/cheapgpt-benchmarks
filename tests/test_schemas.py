import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_release_index_matches_schema() -> None:
    schema = json.loads((ROOT / "schemas/release-index.schema.json").read_text())
    index = json.loads((ROOT / "official/index.json").read_text())

    Draft202012Validator(schema).validate(index)


def test_leaderboard_index_matches_schema() -> None:
    schema = json.loads((ROOT / "schemas/leaderboard-index.schema.json").read_text())
    index = json.loads((ROOT / "leaderboard/index.json").read_text())

    Draft202012Validator(schema).validate(index)


def test_json_schemas_are_valid() -> None:
    for path in (ROOT / "schemas").glob("*.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
