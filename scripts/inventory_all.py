#!/usr/bin/env python
"""STEP 6 acceptance test -- run the intake inventory across the whole catalogue.

Bar: zero crashes on all 53 drawing sets, and the per-set numbers must match
the measured table in RESEARCH.md §2 (page counts, path/text op counts, which
sets are textless, which carry layers).

    python scripts/inventory_all.py                 # all 53 sets
    python scripts/inventory_all.py AB              # just Alberta
    python scripts/inventory_all.py --json out/inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.config import discover  # noqa: E402
from ecarbon.intake import inventory, set_toolchain  # noqa: E402
from ecarbon.models import Toolchain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="", help="substring of the design key")
    ap.add_argument("--json", dest="json_out", default="", help="write full inventory here")
    args = ap.parse_args()

    designs = [d for d in discover() if d.drawings_pdf]
    if args.filter:
        designs = [d for d in designs if args.filter.lower() in d.key.lower()]
    if not designs:
        print(f"no designs matched {args.filter!r}", file=sys.stderr)
        return 2

    print(f"{len(designs)} drawing sets\n")
    hdr = "%-42s %4s %4s %9s %8s %5s %5s  %-20s %s"
    print(hdr % ("design", "pg", "rd", "paths", "text", "lyr", "rvt", "toolchain", "s"))
    print("-" * 125)

    failures: list[tuple[str, str]] = []
    payload: dict[str, object] = {}
    totals = {"pages": 0, "unreadable": 0}
    by_toolchain: dict[str, int] = {}

    for d in designs:
        t0 = time.perf_counter()
        try:
            sheets, probes, producer = inventory(d.drawings_pdf)
        except Exception:
            failures.append((d.key, traceback.format_exc(limit=3)))
            print(hdr % (d.key[:42], "-", "-", "-", "-", "-", "-", "CRASH", "-"))
            continue
        dt = time.perf_counter() - t0

        n_paths = sum(s.n_paths for s in sheets)
        n_text = sum(s.n_text for s in sheets)
        n_read = sum(1 for s in sheets if s.readable)
        n_lyr = len({n for s in sheets for n in s.layer_names})
        n_rvt = sum(1 for s in sheets if s.toolchain is Toolchain.REVIT_TAGGED)
        dom = set_toolchain(sheets)

        totals["pages"] += len(sheets)
        totals["unreadable"] += len(sheets) - n_read
        by_toolchain[dom.value] = by_toolchain.get(dom.value, 0) + 1

        print(
            hdr
            % (
                d.key[:42],
                len(sheets),
                n_read,
                f"{n_paths:,}",
                f"{n_text:,}",
                n_lyr,
                n_rvt,
                dom.value,
                f"{dt:.1f}",
            )
        )

        payload[d.key] = {
            "region": d.region,
            "typology": d.typology,
            "source_file": str(d.drawings_pdf),
            "producer": producer,
            "dominant_toolchain": dom.value,
            "has_ifc": d.has_ifc,
            "n_h2k": len(d.h2k),
            "n_bpr": len(d.bpr),
            "has_list_of_drawings": d.list_of_drawings is not None,
            "sheets": [s.model_dump(mode="json") for s in sheets],
        }

    print("-" * 125)
    print(f"pages: {totals['pages']}   unreadable pages: {totals['unreadable']}")
    print("dominant toolchain across sets: " + ", ".join(f"{k}={v}" for k, v in sorted(by_toolchain.items())))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1))
        print(f"wrote {out}")

    if failures:
        print(f"\n{len(failures)} CRASHES -- Step 6 bar is zero:", file=sys.stderr)
        for key, tb in failures:
            print(f"\n--- {key} ---\n{tb}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
