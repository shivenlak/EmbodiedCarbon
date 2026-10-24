"""Extraction and reconciliation of windows and doors from floor plans and schedules.

Cross-references:
  - Opening tags (WA01, WB02, DA01, DB01, etc.) detected on floor plan sheets.
  - ScheduledOpening objects parsed from the Openings Schedule.

Produces:
  - Total window count & window area (m2)
  - Exterior door count & exterior door area (m2)
  - Interior door count & interior door area (m2)
  - Total opening deduction area (m2) for exterior wall calculation
  - Provenance and confidence (measured when schedule + plan tag match)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from ecarbon.extract.schedules import ScheduledOpening


@dataclass
class OpeningInstance:
    """An individual window or door instance spotted on a floor plan."""

    tag: str
    category: str  # "window" or "door"
    is_exterior: bool
    width_mm: float
    height_mm: float
    area_m2: float
    page: int
    sheet_no: str
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class OpeningsSummary:
    """Aggregated opening quantities for the whole building."""

    total_window_count: int = 0
    total_window_area_m2: float = 0.0
    exterior_door_count: int = 0
    exterior_door_area_m2: float = 0.0
    interior_door_count: int = 0
    interior_door_area_m2: float = 0.0
    total_exterior_opening_area_m2: float = 0.0

    # Tag counts: tag -> count
    tag_counts: dict[str, int] = field(default_factory=dict)
    instances: list[OpeningInstance] = field(default_factory=list)
    confidence: str = "measured"
    unmatched_tags: list[str] = field(default_factory=list)


_WIN_TAG_RE = re.compile(r"\b(W[A-C][0-9]{2})\b")
_DOOR_TAG_RE = re.compile(r"\b(D[A-D][0-9]{2})\b")


def extract_openings_from_plans(
    doc: pymupdf.Document,
    scheduled_openings: dict[str, ScheduledOpening],
    floor_plan_pages: list[tuple[int, str]],  # list of (page_idx, sheet_no)
) -> OpeningsSummary:
    """Spot opening tags across floor plan sheets and correlate with scheduled dimensions."""
    tag_counts: dict[str, int] = {}
    instances: list[OpeningInstance] = []
    unmatched: list[str] = []

    # Default fallback sizes in mm if not in schedule
    DEFAULT_WIN_SIZE = (900.0, 1200.0)  # ~1.08 m2
    DEFAULT_EXT_DOOR_SIZE = (965.0, 2100.0)  # ~2.03 m2
    DEFAULT_INT_DOOR_SIZE = (813.0, 2032.0)  # ~1.65 m2

    for p_idx, s_no in floor_plan_pages:
        page = doc[p_idx]
        blocks = page.get_text("blocks")

        for b in blocks:
            text = b[4].strip()
            # Search for window tags
            for wtag in _WIN_TAG_RE.findall(text):
                tag_counts[wtag] = tag_counts.get(wtag, 0) + 1
                sched = scheduled_openings.get(wtag)
                w_mm, h_mm = (sched.width_mm, sched.height_mm) if sched else DEFAULT_WIN_SIZE
                if not sched and wtag not in unmatched:
                    unmatched.append(wtag)

                area = (w_mm / 1000.0) * (h_mm / 1000.0)
                instances.append(
                    OpeningInstance(
                        tag=wtag,
                        category="window",
                        is_exterior=True,
                        width_mm=w_mm,
                        height_mm=h_mm,
                        area_m2=round(area, 3),
                        page=p_idx,
                        sheet_no=s_no,
                        bbox=(b[0], b[1], b[2], b[3]),
                    )
                )

            # Search for door tags
            for dtag in _DOOR_TAG_RE.findall(text):
                tag_counts[dtag] = tag_counts.get(dtag, 0) + 1
                sched = scheduled_openings.get(dtag)
                is_ext = dtag.startswith("DA") or (sched.is_exterior if sched else False)
                w_mm, h_mm = (
                    (sched.width_mm, sched.height_mm)
                    if sched
                    else (DEFAULT_EXT_DOOR_SIZE if is_ext else DEFAULT_INT_DOOR_SIZE)
                )
                if not sched and dtag not in unmatched:
                    unmatched.append(dtag)

                area = (w_mm / 1000.0) * (h_mm / 1000.0)
                instances.append(
                    OpeningInstance(
                        tag=dtag,
                        category="door",
                        is_exterior=is_ext,
                        width_mm=w_mm,
                        height_mm=h_mm,
                        area_m2=round(area, 3),
                        page=p_idx,
                        sheet_no=s_no,
                        bbox=(b[0], b[1], b[2], b[3]),
                    )
                )

    # Compute aggregates
    win_instances = [inst for inst in instances if inst.category == "window"]
    ext_door_instances = [inst for inst in instances if inst.category == "door" and inst.is_exterior]
    int_door_instances = [inst for inst in instances if inst.category == "door" and not inst.is_exterior]

    win_area = sum(inst.area_m2 for inst in win_instances)
    ext_door_area = sum(inst.area_m2 for inst in ext_door_instances)
    int_door_area = sum(inst.area_m2 for inst in int_door_instances)

    confidence = "measured" if len(unmatched) <= 2 else "inferred"

    return OpeningsSummary(
        total_window_count=len(win_instances),
        total_window_area_m2=round(win_area, 2),
        exterior_door_count=len(ext_door_instances),
        exterior_door_area_m2=round(ext_door_area, 2),
        interior_door_count=len(int_door_instances),
        interior_door_area_m2=round(int_door_area, 2),
        total_exterior_opening_area_m2=round(win_area + ext_door_area, 2),
        tag_counts=tag_counts,
        instances=instances,
        confidence=confidence,
        unmatched_tags=unmatched,
    )
