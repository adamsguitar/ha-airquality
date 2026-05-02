#!/usr/bin/env python3
"""Sync the JSON schema from shared/ into the integration package.

The shared/schema/ directory is the single source of truth. This script copies
the schema into custom_components/airquality/schema/ so the integration can
load it at runtime without importing from outside its own package.

Usage:
    python scripts/sync_schema.py          # copy (overwrites destination)
    python scripts/sync_schema.py --check  # fail with exit code 1 if out of sync
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "shared" / "schema"
DESTINATIONS = [
    ROOT / "custom_components" / "airquality" / "schema",
    ROOT / "addon" / "schema",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check only, do not write")
    args = parser.parse_args()

    if not SRC.is_dir():
        print(f"ERROR: source directory not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    out_of_sync: list[str] = []

    for dst_dir in DESTINATIONS:
        dst_dir.mkdir(parents=True, exist_ok=True)

        for src_file in sorted(SRC.glob("*.json")):
            dst_file = dst_dir / src_file.name
            src_content = json.loads(src_file.read_text(encoding="utf-8"))

            label = f"{dst_dir.relative_to(ROOT)}/{src_file.name}"

            if dst_file.exists():
                dst_content = json.loads(dst_file.read_text(encoding="utf-8"))
                if src_content == dst_content:
                    print(f"  OK  {label}")
                    continue

            if args.check:
                print(f"  OUT OF SYNC  {label}", file=sys.stderr)
                out_of_sync.append(label)
            else:
                dst_file.write_text(
                    json.dumps(src_content, indent=2) + "\n", encoding="utf-8"
                )
                print(f"  SYNCED  {label}")

    if out_of_sync:
        print(
            f"\n{len(out_of_sync)} file(s) out of sync. "
            "Run `python scripts/sync_schema.py` to fix.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.check:
        print("Schema sync complete.")


if __name__ == "__main__":
    main()
