#!/usr/bin/env python3
"""Run the pipeline for every bundled design and save the result.

A drawing set takes about 23 seconds to parse on a shared core, and 177 for
the largest in the catalogue. Until now that cost fell on whoever opened the
link first, and it fell again after every restart, because the only cache was
in memory. For a service whose entire job is to be opened and looked at once,
that is the wrong place to pay.

This pays it at image-build time instead. The takeoff is a pydantic model, so
it round-trips through JSON exactly -- no second code path, no risk that a
prebuilt answer differs from a computed one. Carbon is still recomputed on
load, because it is cheap and because it must follow the factor store rather
than a snapshot taken when the image was built.

    python deploy/prebuild.py            # everything under $EC_DATA
    python deploy/prebuild.py AB_Sixplex # or one design
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Written next to the drawings so the API can find it without being told, and
# so a stale file is obvious: it sits beside the PDF it was built from.
from ecarbon.prebuilt import PREBUILT_DIRNAME, prebuilt_path  # noqa: E402


def facts_for(design, key: str):
    """The project facts the API would use for this design."""
    from ecarbon.models import ProjectFacts

    facts = ProjectFacts(name=key)
    try:
        from ecarbon.bench.bpr import parse_bpr

        if design.bpr:
            bpr = parse_bpr(str(design.bpr[0]))
            facts.jurisdiction = bpr.location
            facts.gfa_m2 = bpr.best_gfa_m2
            facts.gfa_basis = "gross"
            facts.storeys = bpr.storeys
            facts.units = bpr.units
    except Exception:
        pass
    return facts


def build_all(only: tuple[str, ...]) -> int:
    from ecarbon.config import data_root, discover
    from ecarbon.takeoff.builder import build_takeoff

    root = Path(data_root())
    designs = discover()
    if only:
        designs = [
            d for d in designs if any(o.lower() in d.key.lower() for o in only)
        ]
    if not designs:
        print("No designs found. Is $EC_DATA set?", file=sys.stderr)
        return 1

    out_dir = root / PREBUILT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0

    for design in designs:
        started = time.time()
        try:
            takeoff = build_takeoff(design, facts_for(design, design.key))
        except Exception as exc:
            failures += 1
            print(f"  {design.key[:44]:44} FAILED  {exc}", file=sys.stderr)
            continue

        target = prebuilt_path(root, design.key)
        target.write_text(takeoff.model_dump_json(), encoding="utf-8")
        size = target.stat().st_size / 1024
        print(
            f"  {design.key[:44]:44} {time.time() - started:>6.1f}s  "
            f"{len(takeoff.lines):>2} lines  {size:>6.0f} kB"
        )

    print(f"\n  written to {out_dir}")
    if failures:
        print(f"  {failures} design(s) failed and will be parsed on request")
    return 0


if __name__ == "__main__":
    raise SystemExit(build_all(tuple(sys.argv[1:])))
