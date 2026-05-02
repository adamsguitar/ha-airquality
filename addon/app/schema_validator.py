"""JSON Schema validation against the shared airquality schema."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

_SCHEMA_PATH = Path(__file__).parent / "schema" / "airquality.schema.json"


def _validator() -> Draft7Validator:
    with _SCHEMA_PATH.open() as f:
        schema = json.load(f)
    return Draft7Validator(schema)


def validate(data: Any) -> list[str]:
    """Validate parsed YAML data. Returns a list of error messages (empty if valid)."""
    if data is None:
        return ["Configuration is empty."]

    errors = []
    for err in _validator().iter_errors(data):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")
    return errors
