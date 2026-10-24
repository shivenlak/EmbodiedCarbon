#!/usr/bin/env python
"""Locate (or help a teammate obtain) the CMHC catalogue, and report its health.

The catalogue is NOT in the repo and must not be committed: CMHC's Terms and
Conditions grant only a limited licence to adapt the Designs for a specific
Canadian building project and expressly prohibit redistribution. See
RESEARCH.md §7. So this script checks and guides; it does not mirror.

    python scripts/fetch_data.py --check      # inventory what is on disk
    python scripts/fetch_data.py --how        # how to download it yourself
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXPECTED_PACKAGES = 52
EXPECTED_DRAWING_SETS = 53  # ATL_Fourplex_01 ships two options
EXPECTED_BY_REGION = {"AB": 7, "ATL": 8, "BC": 7, "NOR": 9, "ON": 7, "QC": 7, "SKMB": 7}

HOW = """
How to get the data
-------------------
1. Go to https://www.housingcatalogue.cmhc-schl.gc.ca/
2. Download the Technical Design Package for all 52 designs
   (AB x7, ATL x8, BC x7, NOR x9, ON x7, QC x7, SKMB x7).
3. Unzip each so the tree looks like:

       $EC_DATA/
         AB_Fourplex_01_Technical_Design_Package/
           AB_Fourplex_01_Drawings.pdf
           AB_Fourplex_01_BIM/AB_Fourplex_01.ifc
           AB_Fourplex_01_CAD/...
           AB_Fourplex_01_Energy and Carbon/...
         ...

4. export EC_DATA=~/ec-data/cmhc     (add it to your shell profile)
5. python scripts/fetch_data.py --check

While you are there, also grab the Construction Cost Estimates for each design.
They contain published quantity take-offs (CIQS Class B, +/-15%) and are the
closest thing to a reference takeoff available -- see RESEARCH.md §6. They are
NOT part of the Technical Design Package.

Do not commit any of it. .gitignore blocks it; never override with `git add -f`.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="inventory what is on disk")
    ap.add_argument("--how", action="store_true", help="print download instructions")
    args = ap.parse_args()

    if args.how or not args.check:
        print(HOW)
        if not args.check:
            return 0

    try:
        from ecarbon.config import data_root, discover
    except Exception as exc:
        print(f"cannot import ecarbon.config: {exc}")
        return 1

    try:
        root = data_root()
    except FileNotFoundError as exc:
        print(exc)
        print(HOW)
        return 1

    designs = discover()
    packages = {d.package_dir for d in designs}
    print(f"EC_DATA = {root}")
    print(f"packages: {len(packages)} (expected {EXPECTED_PACKAGES})")
    print(f"drawing sets: {sum(1 for d in designs if d.drawings_pdf)} (expected {EXPECTED_DRAWING_SETS})")

    by_region = Counter(d.region for d in designs)
    print("\nby region (design entries; ATL counts 9 because Fourplex_01 has two options):")
    for region, expected in EXPECTED_BY_REGION.items():
        got = by_region.get(region, 0)
        flag = "" if got >= expected else f"   <-- expected >= {expected}"
        print(f"  {region:5} {got}{flag}")

    missing_pdf = [d.key for d in designs if not d.drawings_pdf]
    missing_ifc = [d.key for d in designs if not d.has_ifc]
    missing_lod = [d.key for d in designs if not d.list_of_drawings]
    no_h2k = [d.key for d in designs if not d.h2k]

    print(f"\nIFC present:              {sum(1 for d in designs if d.has_ifc)}/{len(designs)}")
    print(f"HOT2000 present:          {sum(1 for d in designs if d.h2k)}/{len(designs)}")
    print(f"List of Drawings present: {sum(1 for d in designs if d.list_of_drawings)}/{len(designs)}")

    if missing_pdf:
        print(f"\nNO DRAWINGS PDF: {missing_pdf}")
    if missing_ifc:
        print(f"no IFC: {missing_ifc}")
    if missing_lod:
        print(f"no List of Drawings (expected: ATL_Fourplex_03): {missing_lod}")
    if no_h2k:
        print(f"no HOT2000 (expected: the 7 BC designs): {sorted(no_h2k)}")

    ok = len(packages) >= EXPECTED_PACKAGES and not missing_pdf
    print("\n" + ("catalogue looks complete." if ok else "catalogue INCOMPLETE -- see --how"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
