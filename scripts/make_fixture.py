#!/usr/bin/env python
"""Dump the contract fixtures to tests/fixtures/ as JSON.

The UI reads these directly, so they are committed. Re-run after any change to
ecarbon/models.py or ecarbon/fixtures.py, and tell the other person.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.fixtures import example_carbon, example_takeoff  # noqa: E402
from ecarbon.models import SCHEMA_VERSION  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    takeoff = example_takeoff()
    carbon = example_carbon(takeoff)
    for name, doc in (("takeoff_example.json", takeoff), ("carbon_example.json", carbon)):
        path = OUT / name
        path.write_text(doc.model_dump_json(indent=2) + "\n")
        print(f"wrote {path.relative_to(OUT.parent.parent)}  ({path.stat().st_size:,} bytes)")
    print(f"schema version {SCHEMA_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
