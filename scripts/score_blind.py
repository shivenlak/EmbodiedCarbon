#!/usr/bin/env python
"""Score the reading pipeline, stage by stage, on plan sets from outside CMHC.

    python scripts/score_blind.py --split dev        # Stream A
    python scripts/score_blind.py --split holdout    # Stream B only (blind)

Truth is read by eye off each set's drawings into corpus/<split>_truth.yaml;
the sets themselves live in ~/ec-data/global/<id>/ (scripts/fetch_corpus.py).
Writes out/blind.json (contract C6, docs/finals/SHARED.md) and prints a table.

`score_set` is imported by scripts/accuracy.py so both splits are scored the
same way, so this module does no work at import time.

Each failure becomes a `broke` string that names the stage and carries no
numbers, so the strings can be counted across sets into a failure list.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.config import pdf_designs  # noqa: E402
from ecarbon.models import SheetType  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAN_TYPES = {SheetType.FLOOR_PLAN, SheetType.FOUNDATION_PLAN}


def _corpus_root() -> Path:
    # As scripts/fetch_corpus.py.
    return Path(os.environ.get("EC_GLOBAL", Path.home() / "ec-data" / "global"))


def score_set(design_dir: Path, truth: dict | None) -> dict:
    """One C6 row for the plan set in `design_dir`, against `truth` (may be None)."""
    from ecarbon.extract.openings import openings_for
    from ecarbon.intake.inventory import inventory
    from ecarbon.takeoff.builder import (
        ELEMENT_CARBON_SHARE,
        build_takeoff,
        coverage_report,
        gather,
    )

    truth = truth or {}
    broke: list[str] = []
    design = pdf_designs(Path(design_dir))[0]

    sheets, _, _ = inventory(design.drawings_pdf, with_scale=True)
    readable = [s for s in sheets if s.readable]
    typed = [s for s in readable if s.sheet_type is not SheetType.UNKNOWN]
    sheets_ok = len(typed) / len(readable) if readable else 0.0
    if not readable:
        broke.append("sheets: no page has readable text")
    kinds = {s.sheet_type for s in typed}
    for kind in (SheetType.FLOOR_PLAN, SheetType.SECTION, SheetType.ASSEMBLY_SCHEDULE):
        if kind not in kinds:
            broke.append(f"sheets: no {kind.value.replace('_', ' ')} classified")

    plans = [s for s in readable if s.sheet_type in PLAN_TYPES]
    scale_ok = any(s.scale for s in plans)
    if plans and not scale_ok:
        broke.append("scale: none read on any plan sheet")

    # gather() is run again inside build_takeoff; scoring the stages needs its
    # inputs, which the takeoff does not keep.
    inputs, _, _ = gather(design)

    fp = inputs.footprint
    footprint_err_pct = None
    want = truth.get("footprint_m")
    if fp is None:
        broke.append("footprint: none found")
    elif want:
        true_area = truth.get("footprint_area_m2") or want[0] * want[1]
        footprint_err_pct = round(100 * (fp.area_m2 - true_area) / true_area, 1)
        if abs(footprint_err_pct) > 10:
            broke.append("footprint: area off by more than 10%")

    h = inputs.heights
    storeys_ok = None
    if not h.floors:
        broke.append("levels: no floor datum read")
    if truth.get("storeys") is not None:
        storeys_ok = h.n_storeys == truth["storeys"]
        if h.floors and not storeys_ok:
            broke.append("levels: wrong storey count")
    heights_err_m = None
    got_h, want_h = h.storey_heights_m(), truth.get("storey_heights_m")
    if got_h and want_h and len(got_h) == len(want_h):
        heights_err_m = round(max(abs(a - b) for a, b in zip(got_h, want_h, strict=True)), 3)
        if heights_err_m > 0.15:
            broke.append("levels: storey height off by more than 150 mm")

    if not inputs.assemblies:
        broke.append("assemblies: none read")
    for m in inputs.spec.missing:
        broke.append(f"foundation: {m.split(' -- ')[0]}")

    try:
        openings, _ = openings_for(design)
    except Exception:  # noqa: BLE001 -- a crash is a failure to record, not to raise
        openings = []
        broke.append("openings: reader crashed")
    if not openings:
        broke.append("openings: no schedule read")
    openings_err = None
    if truth.get("windows") is not None and truth.get("doors") is not None:
        got = {k: sum(o.count for o in openings if o.kind == k) for k in ("window", "door")}
        openings_err = abs(got["window"] - truth["windows"]) + abs(got["door"] - truth["doors"])

    takeoff = build_takeoff(design)
    # As scripts/run_pipeline.py: classes the takeoff reports as absent from
    # this building leave the denominator.
    absent = {
        cls
        for cls in ELEMENT_CARBON_SHARE
        if any(
            g.message.startswith(f"No {cls.value.replace('_', ' ')} is counted")
            for g in takeoff.gaps
        )
    }
    covered, _ = coverage_report(takeoff.lines, absent)
    if not takeoff.lines:
        broke.append("takeoff: no quantities")

    return {
        "set": Path(design_dir).name,
        "split": truth.get("split"),
        "country": truth.get("country"),
        "units": truth.get("units"),
        "sheets_ok": round(sheets_ok, 2),
        "scale_ok": scale_ok,
        "footprint_err_pct": footprint_err_pct,
        "storeys_ok": storeys_ok,
        "heights_err_m": heights_err_m,
        "assemblies_found": len(inputs.assemblies),
        "openings_err": openings_err,
        "coverage_pct": round(100 * covered, 1),
        "vision_used": any(ln.basis.note.startswith("vision: ") for ln in takeoff.lines),
        "broke": broke,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--split", choices=["dev", "holdout"], default="dev")
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "blind.json")
    args = ap.parse_args(argv)

    sources = yaml.safe_load((ROOT / "corpus" / "sources.yaml").read_text(encoding="utf-8"))
    truth_file = ROOT / "corpus" / f"{args.split}_truth.yaml"
    truths = yaml.safe_load(truth_file.read_text(encoding="utf-8")) if truth_file.is_file() else {}
    root = _corpus_root()

    rows = []
    for entry in sources["sets"]:
        if entry.get("split") != args.split:
            continue
        set_dir = root / entry["id"]
        if not any(set_dir.glob("*.pdf")):
            print(f"{entry['id']:28} not on disk; run scripts/fetch_corpus.py")
            continue
        truth = {**entry, **((truths or {}).get(entry["id"]) or {})}
        row = score_set(set_dir, truth)
        rows.append(row)
        print(
            f"{row['set']:28} sheets {row['sheets_ok']:.0%}  scale {'y' if row['scale_ok'] else 'n'}"
            f"  fp {row['footprint_err_pct'] if row['footprint_err_pct'] is not None else '-':>6}"
            f"  storeys {row['storeys_ok']}  asm {row['assemblies_found']:>2}"
            f"  open-err {row['openings_err'] if row['openings_err'] is not None else '-':>3}"
            f"  cov {row['coverage_pct']:>5.1f}%  broke {len(row['broke'])}"
        )

    # The failure list: each stage failure by how many sets it blocks.
    counts: dict[str, int] = {}
    for row in rows:
        for b in set(row["broke"]):
            counts[b] = counts.get(b, 0) + 1
    if counts:
        print("\nfailures, by sets blocked:")
        for b, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:>2}  {b}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # The other split's rows are kept, so dev and holdout share one file.
    old = json.loads(args.out.read_text()) if args.out.is_file() else []
    keep = [r for r in old if r.get("split") != args.split]
    args.out.write_text(json.dumps(keep + rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
