from __future__ import annotations

from pathlib import Path


def addon_version() -> str:
    """Version from addon `config.yaml` copied into the image as `addon_config.yaml`."""
    p = Path(__file__).resolve().parent / "addon_config.yaml"
    if not p.is_file():
        return "dev"
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "dev"


ADDON_VERSION = addon_version()
