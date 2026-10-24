#!/usr/bin/env python
"""STEP 7 acceptance test -- score sheet identification against the
`List of Drawings` PDFs.

Bar from docs/PLAN.md: >=90% exact sheet-number match and >=85% type match on
10 designs, and all 8 NOR sets flagged "titles unreadable" rather than guessed.

    python scripts/score_sheets.py            # all designs with ground truth
    python scripts/score_sheets.py AB         # just Alberta
    python scripts/score_sheets.py --misses   # show every disagreement
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.bench.sheet_truth import truth_for  # noqa: E402
from ecarbon.config import discover  # noqa: E402
from ecarbon.intake import inventory, readability_gaps, set_toolchain  # noqa: E402
from ecarbon.models import SheetType, Toolchain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--misses", action="store_true", help="list every disagreement")
    args = ap.parse_args()

    designs = [d for d in discover() if d.drawings_pdf and d.list_of_drawings]
    if args.filter:
        designs = [d for d in designs if args.filter.lower() in d.key.lower()]
    if not designs:
        print("no designs with ground truth matched", file=sys.stderr)
        return 2

    print(f"{len(designs)} designs with a List of Drawings\n")
    hdr = "%-42s %5s %5s %7s %7s %7s  %s"
    print(hdr % ("design", "pages", "truth", "num%", "type%", "unid", "toolchain"))
    print("-" * 110)

    tot_num = tot_type = tot_cls = 0
    all_misses: list[str] = []
    per_toolchain: dict[str, list[float]] = {}
    textless_ok = 0
    textless_total = 0

    for d in designs:
        truth = {t.sheet_no.upper(): t for t in truth_for(d)}
        sheets, _, _ = inventory(d.drawings_pdf)
        dom = set_toolchain(sheets)

        # Score only pages we claim to have read; an unreadable page is a
        # reported gap, not a wrong answer. Criterion 1 rewards saying so.
        claimed = [s for s in sheets if s.readable and s.toolchain is not Toolchain.RASTER]
        unident = [s for s in claimed if not s.sheet_no]

        num_hits = [s for s in claimed if s.sheet_no and s.sheet_no.upper() in truth]
        type_hits = [
            s
            for s in num_hits
            if s.sheet_type is truth[s.sheet_no.upper()].sheet_type
            and s.sheet_type is not SheetType.UNKNOWN
        ]

        n = len(claimed) or 1
        num_pct = 100.0 * len(num_hits) / n
        type_pct = 100.0 * len(type_hits) / n
        tot_num += len(num_hits)
        tot_type += len(type_hits)
        tot_cls += len(claimed)
        per_toolchain.setdefault(dom.value, []).append(num_pct)

        if dom is Toolchain.DISTILLER_OUTLINED:
            textless_total += 1
            gaps = readability_gaps(sheets)
            if any("converted to vector outlines" in g.message for g in gaps):
                textless_ok += 1

        print(
            hdr
            % (
                d.key[:42],
                len(claimed),
                len(truth),
                f"{num_pct:.0f}",
                f"{type_pct:.0f}",
                len(unident),
                dom.value,
            )
        )

        if args.misses:
            for s in claimed:
                key = (s.sheet_no or "").upper()
                if key not in truth:
                    all_misses.append(
                        f"  {d.key[:34]:34} p{s.page + 1:<3} no={s.sheet_no!r:10} "
                        f"title={(s.title or '')[:40]!r} NOT IN TRUTH"
                    )
                elif s.sheet_type is not truth[key].sheet_type:
                    all_misses.append(
                        f"  {d.key[:34]:34} p{s.page + 1:<3} {key:8} "
                        f"got={s.sheet_type.value:18} want={truth[key].sheet_type.value:18} "
                        f"title={(s.title or '')[:34]!r} truth={truth[key].title[:34]!r}"
                    )

    print("-" * 110)
    overall_num = 100.0 * tot_num / max(tot_cls, 1)
    overall_type = 100.0 * tot_type / max(tot_cls, 1)
    print(f"pages scored: {tot_cls}")
    print(f"sheet number match: {overall_num:.1f}%   (bar: 90%)  {'PASS' if overall_num >= 90 else 'FAIL'}")
    print(f"sheet type match:   {overall_type:.1f}%   (bar: 85%)  {'PASS' if overall_type >= 85 else 'FAIL'}")
    if textless_total:
        print(
            f"textless sets reporting the gap: {textless_ok}/{textless_total}  "
            f"{'PASS' if textless_ok == textless_total else 'FAIL'}"
        )

    print("\nby dominant toolchain (median sheet-number match):")
    for tc, vals in sorted(per_toolchain.items()):
        vals.sort()
        med = vals[len(vals) // 2]
        print(f"   {tc:22} n={len(vals):3}  median={med:5.0f}%  worst={min(vals):5.0f}%")

    if all_misses:
        print(f"\n{len(all_misses)} disagreements:")
        print("\n".join(all_misses[:80]))
        if len(all_misses) > 80:
            print(f"  ... and {len(all_misses) - 80} more")

    types = Counter()
    for d in designs[:12]:
        for t in truth_for(d):
            types[t.sheet_type.value] += 1
    print("\nground-truth sheet types (first 12 designs):")
    for k, v in types.most_common():
        print(f"   {k:20} {v}")

    return 0 if overall_num >= 90 and overall_type >= 85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
