#!/usr/bin/env python
"""STEP 10 -- score footprint extraction against the IFC envelope.

The footprint feeds two of the biggest carbon items: slab volume (area x the
stated thickness) and exterior wall area (perimeter x storey height). An error
here scales both.

Only designs whose IFC geometry is complete can be scored; the rest are
reported as unscoreable rather than counted as passes.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.bench.ifc_truth import building_bbox, geometry_coverage  # noqa: E402
from ecarbon.config import discover  # noqa: E402
from ecarbon.geometry.footprint import detect_footprint  # noqa: E402
from ecarbon.geometry.scale import calibrate  # noqa: E402
from ecarbon.intake import inventory  # noqa: E402
from ecarbon.models import SheetType  # noqa: E402

PLAN_TYPES = {SheetType.FLOOR_PLAN, SheetType.FOUNDATION_PLAN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="")
    args = ap.parse_args()

    designs = [d for d in discover() if d.drawings_pdf and d.ifc]
    if args.filter:
        designs = [d for d in designs if args.filter.lower() in d.key.lower()]

    hdr = "%-40s %-6s %-15s %-15s %7s %6s %7s"
    print(hdr % ("design", "sheet", "PDF (m)", "IFC (m)", "err%", "strokeW", "agree%"))
    print("-" * 104)

    errors: list[float] = []
    undetected: list[str] = []
    unscoreable: list[str] = []

    for d in designs:
        try:
            sheets, _, _ = inventory(d.drawings_pdf)
        except Exception:
            undetected.append(d.key)
            continue
        cov = geometry_coverage(str(d.ifc))
        bbox = building_bbox(str(d.ifc)) if cov.usable else None
        ifc = [x / 1000.0 for x in bbox.plan_mm] if bbox else None

        doc = pymupdf.open(d.drawings_pdf)
        fp = sheet = None
        try:
            for s in [x for x in sheets if x.sheet_type in PLAN_TYPES and x.readable][:4]:
                got = detect_footprint(doc[s.page], calibrate(doc[s.page]))
                if got and got.confident:
                    fp, sheet = got, s
                    break
                if got and fp is None:
                    fp, sheet = got, s
        finally:
            doc.close()

        if fp is None:
            undetected.append(d.key)
            print(hdr % (d.key[:40], "-", "not detected", "-", "-", "-", "-"))
            continue
        if ifc is None:
            unscoreable.append(d.key)
            print(hdr % (d.key[:40], sheet.sheet_no or "?",
                         f"{fp.plan_m[0]:.2f}x{fp.plan_m[1]:.2f}", "ifc degraded",
                         "-", fp.stroke_width, fp.agreement_pct))
            continue

        err = max(100.0 * abs(a - b) / b for a, b in zip(fp.plan_m, ifc, strict=False))
        errors.append(err)
        print(hdr % (d.key[:40], sheet.sheet_no or "?",
                     f"{fp.plan_m[0]:.2f}x{fp.plan_m[1]:.2f}",
                     f"{ifc[0]:.2f}x{ifc[1]:.2f}", f"{err:.1f}",
                     fp.stroke_width, fp.agreement_pct))

    print("-" * 104)
    if errors:
        errors.sort()
        med = statistics.median(errors)
        print(f"scored {len(errors)} designs")
        print(f"  median error {med:.1f}%   worst {errors[-1]:.1f}%")
        for bar in (5.0, 10.0, 15.0, 25.0):
            print(f"  within {bar:>4.0f}%: {sum(1 for e in errors if e <= bar):3}/{len(errors)}")
    if unscoreable:
        print(f"\nIFC degraded, not scoreable ({len(unscoreable)})")
    if undetected:
        print(f"no footprint detected ({len(undetected)}): {', '.join(k[:24] for k in undetected)}")
    return 0 if errors and statistics.median(errors) <= 10.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
