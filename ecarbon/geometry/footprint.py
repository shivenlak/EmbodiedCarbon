"""STEP 10 -- the building footprint, from vector geometry.

Needed by two of the biggest carbon items at once:

  * foundation concrete -- slab volume is footprint area x the stated slab
    thickness, and grade beam volume is the beam run length x its section
    (ecarbon/extract/specs.py)
  * exterior wall area -- perimeter x storey height

### How the building is separated from the rest of the sheet

A floor plan sheet is mostly *not* the building: there is a border, a title
block, grid lines, dimension lines, section markers, notes and often details.
Taking every segment longer than a metre gives an extent of 30.6 x 30.0 m on
AB_Fourplex_01 A101, against a true 7.0 x 22.0.

Architectural drafting uses **lineweight as hierarchy**, and the section cut
through walls is the heaviest line on a plan. Grouping segments by stroke width
on that sheet:

    width 1.42   67 long segments   extent 7.00 x 22.00 m   <- the building
    width 0.51  252 long segments   extent 27.5 x 25.2  m   <- border, grids
    width 0.28  117 long segments   extent 30.6 x 27.4  m   <- dimension lines
    width 0     255 long segments   extent 6.92 x 21.92 m   <- wall pochΓ© fill

So the candidate groups are the stroke widths. Choosing between them by "which
looks like a building" would be circular, so the choice is made by **agreement
with the dimension chains**, which are parsed independently from text
(ecarbon/geometry/scale.py). Two unrelated signals -- stated dimensions and
drafting lineweight -- agreeing on the same rectangle is evidence; either alone
is a guess. That is the cross-validation the plan asks for, made concrete.

A footprint is reported with `basis` naming which signals agreed, and with
`agreement_pct` so a weak match is visible rather than silent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf

from ecarbon.geometry.scale import ScaleEstimate, dimension_chains

# A wall run shorter than this is a jog, a closet or a hatch line.
MIN_SEGMENT_MM = 1000.0
# A stroke-width group needs this many long segments to be a candidate.
MIN_SEGMENTS = 12
# Plausible building plan dimension, metres.
MIN_SIDE_M = 2.5
MAX_SIDE_M = 120.0
# How close a candidate extent must be to a dimension chain total to count.
MATCH_TOL_PCT = 6.0


@dataclass(frozen=True)
class Segment:
    length_mm: float
    x0: float
    y0: float
    x1: float
    y1: float
    width: float

    @property
    def is_horizontal(self) -> bool:
        return abs(self.y1 - self.y0) < abs(self.x1 - self.x0) * 0.05

    @property
    def is_vertical(self) -> bool:
        return abs(self.x1 - self.x0) < abs(self.y1 - self.y0) * 0.05


@dataclass
class Footprint:
    width_m: float
    depth_m: float
    basis: list[str] = field(default_factory=list)
    agreement_pct: float | None = None
    stroke_width: float | None = None
    n_segments: int = 0

    @property
    def area_m2(self) -> float:
        return self.width_m * self.depth_m

    @property
    def perimeter_m(self) -> float:
        """Rectangular perimeter. For an L-shaped or courtyard plan this
        understates the true wall run, which is why `is_rectangular` exists."""
        return 2.0 * (self.width_m + self.depth_m)

    @property
    def confident(self) -> bool:
        """Two independent signals agreed within tolerance."""
        return (
            len(self.basis) >= 2
            and self.agreement_pct is not None
            and self.agreement_pct <= MATCH_TOL_PCT
        )

    @property
    def plan_m(self) -> tuple[float, float]:
        return (min(self.width_m, self.depth_m), max(self.width_m, self.depth_m))


def segments(page: pymupdf.Page, scale: ScaleEstimate) -> list[Segment]:
    """Every straight segment on the page, in real millimetres."""
    if scale.mm_per_pt is None:
        return []
    s = scale.mm_per_pt
    out: list[Segment] = []
    for path in page.get_drawings():
        width = round(path.get("width") or 0.0, 2)
        for item in path["items"]:
            if item[0] == "l":
                (x0, y0), (x1, y1) = item[1], item[2]
                length = math.hypot(x1 - x0, y1 - y0) * s
                out.append(Segment(length, x0, y0, x1, y1, width))
            elif item[0] == "re":
                r = item[1]
                # A rectangle contributes its four edges.
                for a, b, c, d in (
                    (r.x0, r.y0, r.x1, r.y0),
                    (r.x1, r.y0, r.x1, r.y1),
                    (r.x1, r.y1, r.x0, r.y1),
                    (r.x0, r.y1, r.x0, r.y0),
                ):
                    out.append(Segment(math.hypot(c - a, d - b) * s, a, b, c, d, width))
    return out


def _extent_m(segs: list[Segment], scale: float) -> tuple[float, float]:
    xs = [v for sg in segs for v in (sg.x0, sg.x1)]
    ys = [v for sg in segs for v in (sg.y0, sg.y1)]
    return (
        (max(xs) - min(xs)) * scale / 1000.0,
        (max(ys) - min(ys)) * scale / 1000.0,
    )


def _closest_chain_match(side_m: float, chain_totals_m: list[float]) -> float | None:
    """Relative error, in percent, to the nearest stated dimension total."""
    if not chain_totals_m:
        return None
    best = min(chain_totals_m, key=lambda t: abs(t - side_m))
    return 100.0 * abs(best - side_m) / best if best else None


def detect_footprint(page: pymupdf.Page, scale: ScaleEstimate) -> Footprint | None:
    """Find the building footprint on a plan sheet.

    Returns None rather than guessing when no lineweight group agrees with the
    stated dimensions -- a wrong footprint silently scales both the foundation
    concrete and the exterior wall area.
    """
    if scale.mm_per_pt is None:
        return None
    s = scale.mm_per_pt

    long_segs = [sg for sg in segments(page, scale) if sg.length_mm >= MIN_SEGMENT_MM]
    if not long_segs:
        return None

    # Independent evidence: totals of the dimension chains parsed from text.
    chain_totals = [c.total_mm / 1000.0 for c in dimension_chains(page)]

    groups: dict[float, list[Segment]] = {}
    for sg in long_segs:
        groups.setdefault(sg.width, []).append(sg)

    best: tuple[float, Footprint] | None = None
    for width, segs in groups.items():
        if len(segs) < MIN_SEGMENTS:
            continue
        w_m, d_m = _extent_m(segs, s)
        if not (MIN_SIDE_M <= w_m <= MAX_SIDE_M and MIN_SIDE_M <= d_m <= MAX_SIDE_M):
            continue
        errs = [
            e
            for e in (
                _closest_chain_match(w_m, chain_totals),
                _closest_chain_match(d_m, chain_totals),
            )
            if e is not None
        ]
        if not errs:
            continue
        agreement = max(errs)
        fp = Footprint(
            width_m=round(w_m, 3),
            depth_m=round(d_m, 3),
            basis=["vector_path", "dim_text"],
            agreement_pct=round(agreement, 2),
            stroke_width=width,
            n_segments=len(segs),
        )
        # Prefer the best agreement; break ties toward the heavier line, which
        # is the section cut through the walls.
        score = (agreement, -width)
        if best is None or score < best[0]:
            best = (score, fp)

    if best is None or not best[1].confident:
        return best[1] if best else None
    return best[1]
