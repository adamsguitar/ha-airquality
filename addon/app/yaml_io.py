"""YAML I/O with ruamel.yaml round-tripping.

Preserves comments, key ordering, and formatting when the user saves a config
that was read from an existing file. New files use a sensible default style.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

YAML_PATH = Path("/config/airquality.yaml")
PROPOSAL_PATH = Path("/config/airquality.yaml.proposed")


def _yaml() -> YAML:
    """Return a ruamel.yaml instance configured for round-trip preservation."""
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 120
    return y


def load(path: Path = YAML_PATH) -> Any:
    """Load YAML from disk. Returns None if the file doesn't exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return _yaml().load(f)


def load_text(path: Path = YAML_PATH) -> str:
    """Load raw text content of a YAML file. Returns empty string if missing."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def dump_text(data: Any) -> str:
    """Dump a parsed YAML document back to a string, preserving formatting."""
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def save(data: Any, path: Path = YAML_PATH) -> None:
    """Save a parsed YAML document to disk."""
    path.write_text(dump_text(data), encoding="utf-8")


def save_text(text: str, path: Path = YAML_PATH) -> None:
    """Save raw YAML text to disk after parsing it through ruamel for normalization."""
    parsed = _yaml().load(text)
    save(parsed, path)


def parse_text(text: str) -> Any:
    """Parse a YAML string into a ruamel data structure."""
    return _yaml().load(text)
