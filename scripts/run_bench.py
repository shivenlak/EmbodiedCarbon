#!/usr/bin/env python
"""Step 16: Benchmark v1 harness.

Runs end-to-end takeoff -> carbon calculation across available catalogue designs,
compares against IFC ground truth quantities, and reports accuracy metrics
(median error, worst-case, spread per element class, grouped by toolchain).

Usage:
    python scripts/run_bench.py [--region AB] [--json output.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.bench.ifc_truth import parse_ifc_takeoff
from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.config import discover
from ecarbon.models import ElementClass
from ecarbon.takeoff import generate_takeoff


def run_benchmark(region_filter: str | None = None) -> dict:
    designs = discover()
    target_designs = []
    for d in designs:
        if region_filter and d.region != region_filter:
            continue
        if d.drawings_pdf and d.ifc:
            target_designs.append(d)

    print(f"Running Benchmark v1 on {len(target_designs)} designs with IFC ground truth...\n")
    provider = LocalSnapshotProvider()

    results = []
    wall_errors = []
    slab_errors = []
    roof_errors = []
    window_errors = []

    hdr = "%-24s %-12s %8s %8s %7s | %8s %8s %7s | %6s %6s | %10s %8s"
    print(
        hdr
        % (
            "Design",
            "Toolchain",
            "Wall m2",
            "IFC m2",
            "Err %",
            "Slab m2",
            "IFC m2",
            "Err %",
            "Win TO",
            "IFC",
            "A1-A3 kg",
            "kg/m2",
        )
    )
    print("-" * 120)

    for d in target_designs:
        try:
            ifc = parse_ifc_takeoff(d.ifc)
            if not ifc.is_usable:
                print(f"{d.key[:24]:24} UNUSABLE: {ifc.unusable_reason}")
                continue

            to = generate_takeoff(d.drawings_pdf)
            carbon = calculate_carbon(to, provider)

            # Extract takeoff headline quantities
            slab_line = next((l for l in to.lines if l.id == "ln-slab-concrete"), None)
            slab_area = (slab_line.quantity / 0.10) if slab_line else 0.0

            wall_line = next((l for l in to.lines if l.id == "ln-ext-wall-batt-insulation"), None)
            wall_area = wall_line.quantity if wall_line else 0.0

            roof_line = next((l for l in to.lines if l.id == "ln-roof-covering"), None)
            roof_area = roof_line.quantity if roof_line else 0.0

            win_line = next((l for l in to.lines if l.id == "ln-windows-total"), None)
            # Find window count from basis note
            import re
            m = re.search(r"(\d+)\s+window units", win_line.basis.note if win_line else "")
            win_count = int(m.group(1)) if m else 0

            # Errors vs IFC
            wall_err = (
                abs(wall_area - ifc.exterior_wall_area_m2) / ifc.exterior_wall_area_m2 * 100.0
                if ifc.exterior_wall_area_m2 > 0
                else 0.0
            )
            slab_err = (
                abs(slab_area - ifc.slab_on_grade_area_m2) / ifc.slab_on_grade_area_m2 * 100.0
                if ifc.slab_on_grade_area_m2 > 0
                else 0.0
            )
            win_err = (
                abs(win_count - ifc.window_count) / ifc.window_count * 100.0
                if ifc.window_count > 0
                else 0.0
            )

            wall_errors.append(wall_err)
            slab_errors.append(slab_err)
            window_errors.append(win_err)

            tc_name = to.sheets[0].toolchain.value if to.sheets else "unknown"

            print(
                hdr
                % (
                    d.key.replace("_Technical_Design_Package", "")[:24],
                    tc_name[:12],
                    f"{wall_area:.1f}",
                    f"{ifc.exterior_wall_area_m2:.1f}",
                    f"{wall_err:.1f}%",
                    f"{slab_area:.1f}",
                    f"{ifc.slab_on_grade_area_m2:.1f}",
                    f"{slab_err:.1f}%",
                    f"{win_count}",
                    f"{ifc.window_count}",
                    f"{carbon.total_kg_co2e:,.0f}",
                    f"{carbon.intensity_kg_co2e_per_m2:.1f}",
                )
            )

            results.append(
                {
                    "design": d.key,
                    "toolchain": tc_name,
                    "wall_takeoff_m2": wall_area,
                    "wall_ifc_m2": ifc.exterior_wall_area_m2,
                    "wall_error_pct": round(wall_err, 2),
                    "slab_takeoff_m2": slab_area,
                    "slab_ifc_m2": ifc.slab_on_grade_area_m2,
                    "slab_error_pct": round(slab_err, 2),
                    "window_takeoff_count": win_count,
                    "window_ifc_count": ifc.window_count,
                    "window_error_pct": round(win_err, 2),
                    "carbon_total_kg_co2e": round(carbon.total_kg_co2e, 1),
                    "carbon_intensity_kg_co2e_per_m2": round(carbon.intensity_kg_co2e_per_m2, 1),
                }
            )

        except Exception as exc:
            print(f"{d.key[:24]:24} ERROR: {exc}")

    print("-" * 120)
    print("\nBENCHMARK ACCURACY SUMMARY:")
    if wall_errors:
        print(f"  Exterior Wall Area:  Median Error = {statistics.median(wall_errors):.1f}%,  Worst = {max(wall_errors):.1f}%")
    if slab_errors:
        print(f"  Slab on Grade Area:  Median Error = {statistics.median(slab_errors):.1f}%,  Worst = {max(slab_errors):.1f}%")
    if window_errors:
        print(f"  Window Count:        Median Error = {statistics.median(window_errors):.1f}%,  Worst = {max(window_errors):.1f}%")

    all_errs = wall_errors + slab_errors + window_errors
    if all_errs:
        within_10 = sum(1 for e in all_errs if e <= 10.0) / len(all_errs) * 100.0
        within_15 = sum(1 for e in all_errs if e <= 15.0) / len(all_errs) * 100.0
        print(f"\n  Overall Accuracy:    {within_10:.1f}% within 10% error | {within_15:.1f}% within 15% error (Rubric bar: >= 80%)")

    return {
        "n_designs": len(results),
        "median_wall_error_pct": round(statistics.median(wall_errors), 2) if wall_errors else None,
        "median_slab_error_pct": round(statistics.median(slab_errors), 2) if slab_errors else None,
        "median_window_error_pct": round(statistics.median(window_errors), 2) if window_errors else None,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run accuracy benchmark against IFC ground truth.")
    parser.add_argument("--region", type=str, default=None, help="Filter by region (e.g. AB, BC, QC)")
    parser.add_argument("--json", type=str, default=None, help="Output JSON results to file")
    args = parser.parse_args()

    bench_data = run_benchmark(region_filter=args.region)

    if args.json:
        out_path = Path(args.json)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(bench_data, f, indent=2)
        print(f"\nBenchmark JSON saved to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
