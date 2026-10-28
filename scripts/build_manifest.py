#!/usr/bin/env python
"""Build the per-design ground-truth manifest -- the artefact Step 10 scores against.

Joins IFC quantities, HOT2000 envelope areas and the Building Performance
Report for every design, then tiers each one by whether its ground truth is
good enough to attribute a quantity error to the pipeline.

    python scripts/build_manifest.py                  # all designs
    python scripts/build_manifest.py AB               # just Alberta
    python scripts/build_manifest.py --out out/truth.json

Takes a few minutes for the full catalogue: IFC shape building dominates.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.bench.manifest import (  # noqa: E402
    Tier,
    build_design_truth,
    save_manifest,
    summarise,
)
from ecarbon.config import discover  # noqa: E402

DEFAULT_OUT = "out/ground_truth.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    designs = [d for d in discover() if d.drawings_pdf]
    if args.filter:
        designs = [d for d in designs if args.filter.lower() in d.key.lower()]
    if not designs:
        print("no designs matched", file=sys.stderr)
        return 2

    hdr = "%-40s %-7s %5s %6s %8s %8s %8s %7s %7s  %s"
    print(hdr % ("design", "tool", "geom", "walls", "extWall", "h2kWall", "agree%", "concrete", "EC/m2", "tier"))
    print("-" * 126)

    rows = []
    t0 = time.perf_counter()
    for d in designs:
        t = build_design_truth(d)
        rows.append(t)
        print(
            hdr
            % (
                t.key[:40],
                t.dominant_toolchain[:7],
                f"{t.ifc_geometry_coverage*100:.0f}%" if t.ifc_geometry_coverage is not None else "-",
                t.n_walls or "-",
                f"{t.exterior_wall_gross_m2:.0f}" if t.exterior_wall_gross_m2 else "-",
                f"{t.h2k_wall_m2:.0f}" if t.h2k_wall_m2 else "-",
                f"{t.wall_agreement_pct:.1f}" if t.wall_agreement_pct is not None else "-",
                f"{t.concrete_volume_m3:.1f}" if t.concrete_volume_m3 else "-",
                f"{t.bpr_ec_per_gfa:.0f}" if t.bpr_ec_per_gfa else "-",
                t.tier,
            )
        )

    print("-" * 126)
    print(summarise(rows))
    print(f"\nbuilt in {time.perf_counter() - t0:.0f}s")

    gold = [r for r in rows if r.tier == Tier.GOLD]
    if gold:
        print(f"\nGOLD benchmark set ({len(gold)}): " + ", ".join(r.key[:24] for r in gold[:12]))
        if len(gold) > 12:
            print(f"  ... and {len(gold) - 12} more")

    flagged = [r for r in rows if r.flags]
    if flagged:
        print(f"\nflags ({len(flagged)} designs):")
        for r in flagged:
            print(f"  {r.key[:38]:38} {', '.join(r.flags)}")

    path = save_manifest(rows, args.out)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
