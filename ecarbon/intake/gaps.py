"""Stage 1: "Flag what cannot be read. A missing section detail or illegible
schedule should produce a reported gap, not a silent assumption."

The gap report is a first-class output, not an error log. Criterion 1 scores
"reports what it cannot read rather than assuming", so these messages are
user-facing prose and must say what the consequence is, not just what failed.
"""

from __future__ import annotations

from ecarbon.models import Gap, GapCode, GapSeverity, SheetInfo, SheetType, Toolchain

# Sheet types we need before a credible takeoff is possible, and why.
REQUIRED_SHEETS: dict[SheetType, str] = {
    SheetType.FLOOR_PLAN: "floor areas, wall runs and opening positions",
    SheetType.FOUNDATION_PLAN: "slab, footing and foundation-wall concrete",
    SheetType.ROOF_PLAN: "roof area",
    SheetType.SECTION: "storey heights and assembly build-ups",
    SheetType.ASSEMBLY_SCHEDULE: "which materials each assembly tag contains",
    SheetType.OPENING_SCHEDULE: "window and door sizes and counts",
}


def readability_gaps(sheets: list[SheetInfo]) -> list[Gap]:
    """Report unreadable pages, grouped so the user sees a pattern rather than
    forty near-identical rows."""
    gaps: list[Gap] = []

    outlined = [s for s in sheets if s.toolchain is Toolchain.DISTILLER_OUTLINED]
    if outlined:
        pages = ", ".join(str(s.page + 1) for s in outlined[:12])
        more = f" (and {len(outlined) - 12} more)" if len(outlined) > 12 else ""
        share = len(outlined) / len(sheets) if sheets else 0
        gaps.append(
            Gap(
                code=GapCode.PAGE_TEXT_UNREADABLE,
                # If most of the set is affected we cannot produce a takeoff at
                # all; a couple of pages only costs us those pages.
                severity=GapSeverity.BLOCKING if share > 0.5 else GapSeverity.WARNING,
                message=(
                    f"{len(outlined)} of {len(sheets)} pages have their text converted to "
                    f"vector outlines, so no dimension strings, schedules or sheet titles "
                    f"can be read from them (pages {pages}{more}). Geometry is still "
                    f"measurable; quantities from these pages are labelled inferred rather "
                    f"than measured, because the dimension cross-check is unavailable."
                ),
            )
        )

    raster = [s for s in sheets if s.toolchain is Toolchain.RASTER]
    # Page 1 is an image cover sheet in every catalogue set and carries no
    # measurable content, so it is not worth reporting as a problem.
    raster = [s for s in raster if s.page != 0]
    if raster:
        gaps.append(
            Gap(
                code=GapCode.PAGE_TEXT_UNREADABLE,
                severity=GapSeverity.WARNING,
                message=(
                    f"{len(raster)} page(s) are raster images with no vector geometry "
                    f"(pages {', '.join(str(s.page + 1) for s in raster)}). Nothing can be "
                    f"measured from them without OCR."
                ),
            )
        )

    for s in sheets:
        if s.readable and s.sheet_no is None and s.toolchain is not Toolchain.RASTER:
            gaps.append(
                Gap(
                    code=GapCode.SHEET_TITLE_UNKNOWN,
                    severity=GapSeverity.INFO,
                    message=(
                        f"Page {s.page + 1} has readable text but no sheet number was "
                        f"identified, so it is not cross-referenced in the bill of quantities."
                    ),
                    page=s.page,
                )
            )

    return gaps


def coverage_gaps(sheets: list[SheetInfo]) -> list[Gap]:
    """Report required sheet types that are absent from the set."""
    present = {s.sheet_type for s in sheets if s.readable}
    gaps: list[Gap] = []
    for want, why in REQUIRED_SHEETS.items():
        if want in present:
            continue
        code = {
            SheetType.ASSEMBLY_SCHEDULE: GapCode.ASSEMBLY_SCHEDULE_MISSING,
            SheetType.OPENING_SCHEDULE: GapCode.OPENING_SCHEDULE_MISSING,
            SheetType.SECTION: GapCode.SECTION_DETAIL_MISSING,
        }.get(want, GapCode.SHEET_TYPE_MISSING)
        gaps.append(
            Gap(
                code=code,
                severity=GapSeverity.BLOCKING,
                message=(
                    f"No readable {want.value.replace('_', ' ')} was found in this set. "
                    f"It is the source for {why}, so those quantities cannot be produced."
                ),
            )
        )
    return gaps


def summarise(gaps: list[Gap]) -> str:
    """One line for the CLI and the top of the UI panel."""
    if not gaps:
        return "no gaps reported"
    counts: dict[GapSeverity, int] = {}
    for g in gaps:
        counts[g.severity] = counts.get(g.severity, 0) + 1
    return ", ".join(f"{n} {sev.value}" for sev, n in sorted(counts.items(), key=lambda kv: kv[0].value))
