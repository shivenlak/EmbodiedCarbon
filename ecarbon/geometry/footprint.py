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

from ecarbon.geometry.scale import DimLabel, ScaleEstimate, _chains, find_dimension_labels

# A wall run shorter than this is a jog, a closet or a hatch line.
MIN_SEGMENT_MM = 1000.0
# A stroke-width group needs this many long segments to be a candidate.
MIN_SEGMENTS = 12
# Plausible building plan dimension, metres.
MIN_SIDE_M = 2.5
MAX_SIDE_M = 120.0
# How close a candidate extent must be to a dimension chain total to count.
MATCH_TOL_PCT = 6.0
# Residential plans are not extreme slivers; a ratio past this is a sheet
# artefact rather than a building.
MAX_ASPECT_RATIO = 6.0
# How much a unit of relative area error counts against a percentage point of
# dimension disagreement. At 25, a candidate whose area is 1.7x too large pays
# 42 points -- enough to lose to a correct candidate agreeing only to 5%.
AREA_WEIGHT = 25.0
# Hard area bounds, as a multiple of the expected floor area per storey.
# Generous on the high side because for a rowhouse the expected area describes
# ONE UNIT while the drawing shows the whole block (RESEARCH S18), so a correct
# footprint is legitimately a multiple. Tight enough to reject QC_ADU_02's
# 170 m2 sheet artefact for a 61 m2 ADU, which was a 287% error reported with
# 2% dimension agreement -- a confidently wrong number, which is worse than
# none.
AREA_MAX_MULTIPLE = 2.5
AREA_MIN_MULTIPLE = 0.4
# Segments of one stroke width closer than this belong to one drawing. A US
# plan sheet draws the main plan beside option vignettes in the same wall
# stroke, and the whole group's extent spans them all (Escondido ADU 1:
# 24 x 12 m for a 6.7 x 6.7 m building).
CLUSTER_GAP_MM = 600.0
# How far two neighbouring labels' gap may sit from their runs, at the page
# scale, and still be one dimension string.
RUN_SCALE_TOL = 0.15
# A single overall dimension (the US habit: one label outside the wall line)
# counts for a candidate's side only if it sits within this far outside that
# side and is centred on it to this fraction of the side's length.
OVERALL_REACH_MM = 3000.0
OVERALL_CENTRE_TOL = 0.03


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
    # Extent of the outline on the page, in PDF points (x0, y0, x1, y1).
    bbox: tuple[float, float, float, float] | None = None

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


def _clusters(segs: list[Segment], gap_pt: float) -> list[list[Segment]]:
    """Segments grouped by touching bounding boxes, grown by `gap_pt`."""
    parent = list(range(len(segs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = sorted(
        (min(s.x0, s.x1) - gap_pt, min(s.y0, s.y1) - gap_pt, max(s.x0, s.x1) + gap_pt,
         max(s.y0, s.y1) + gap_pt, i)
        for i, s in enumerate(segs)
    )
    for a, box_a in enumerate(boxes):
        for box_b in boxes[a + 1 :]:
            if box_b[0] > box_a[2]:
                break
            if box_a[1] <= box_b[3] and box_b[1] <= box_a[3]:
                parent[root(box_a[4])] = root(box_b[4])
    out: dict[int, list[Segment]] = {}
    for i, s in enumerate(segs):
        out.setdefault(root(i), []).append(s)
    return list(out.values())


def _string_totals_m(labels: list[DimLabel], mm_per_pt: float) -> list[float]:
    """Totals of the dimension strings on the page, in metres.

    Labels sharing a coordinate are split wherever two neighbours are not drawn
    end to end at the page scale: a sheet that draws its plan twice lines up
    both copies' labels, and their sum is a span neither drawing has
    (Riverside ADU 3 matched 16 x 32 m against such sums, for 5 x 13 m).
    """
    out: list[float] = []
    for axis in ("vertical", "horizontal"):
        at = (lambda d: d.y) if axis == "vertical" else (lambda d: d.x)
        for chain in _chains(labels, axis):
            run = [chain[0]]
            for a, b in zip(chain, chain[1:], strict=False):
                drawn = abs(at(b) - at(a)) * mm_per_pt
                if abs(drawn / ((a.value_mm + b.value_mm) / 2.0) - 1.0) > RUN_SCALE_TOL:
                    if len(run) >= 2:
                        out.append(sum(d.value_mm for d in run) / 1000.0)
                    run = []
                run.append(b)
            if len(run) >= 2:
                out.append(sum(d.value_mm for d in run) / 1000.0)
    return out


def _closest_chain_match(side_m: float, chain_totals_m: list[float]) -> float | None:
    """Relative error, in percent, to the nearest stated dimension total."""
    if not chain_totals_m:
        return None
    best = min(chain_totals_m, key=lambda t: abs(t - side_m))
    return 100.0 * abs(best - side_m) / best if best else None


def detect_footprint(
    page: pymupdf.Page,
    scale: ScaleEstimate,
    expected_area_m2: float | None = None,
) -> Footprint | None:
    """Find the building footprint on a plan sheet.

    Returns None rather than guessing when no lineweight group agrees with the
    stated dimensions -- a wrong footprint silently scales both the foundation
    concrete and the exterior wall area.

    `expected_area_m2` is an optional third signal: approximate floor area per
    storey, i.e. gross floor area divided by storey count. Lineweight agreement
    with the dimension chains alone is occasionally fooled, because a chain
    total can describe a site setback rather than the building -- QC_ADU_02
    matched a 30 m span to within 2% and returned a 170 m2 footprint for a
    61 m2 ADU. A floor area is a project fact the scope already requires Stage 1
    to prompt for ("conditioned floor area basis"), so it is legitimately an
    input rather than ground truth leaking in.
    """
    if scale.mm_per_pt is None:
        return None
    s = scale.mm_per_pt

    all_segs = segments(page, scale)
    long_segs = [sg for sg in all_segs if sg.length_mm >= MIN_SEGMENT_MM]
    if not long_segs:
        return None

    # Independent evidence: totals of the dimension chains parsed from text.
    labels = find_dimension_labels(page)
    chain_totals = _string_totals_m(labels, s)
    reach = OVERALL_REACH_MM / s

    def overall_m(box: tuple[float, float, float, float], across_x: bool) -> list[float]:
        """Labels centred just outside one side of `box`, as metres."""
        x0, y0, x1, y1 = box if across_x else (box[1], box[0], box[3], box[2])
        out = []
        for lb in labels:
            u, v = (lb.x, lb.y) if across_x else (lb.y, lb.x)
            centred = abs(u - (x0 + x1) / 2.0) <= OVERALL_CENTRE_TOL * (x1 - x0)
            if centred and (y0 - reach <= v < y0 or y1 < v <= y1 + reach):
                out.append(lb.value_mm / 1000.0)
        return out

    groups: dict[float, list[Segment]] = {}
    for sg in long_segs:
        groups.setdefault(sg.width, []).append(sg)

    def rank(width: float, segs: list[Segment]) -> tuple[tuple[float, float], Footprint] | None:
        if len(segs) < MIN_SEGMENTS:
            return None
        w_m, d_m = _extent_m(segs, s)
        if not (MIN_SIDE_M <= w_m <= MAX_SIDE_M and MIN_SIDE_M <= d_m <= MAX_SIDE_M):
            return None
        short, long = min(w_m, d_m), max(w_m, d_m)
        if short <= 0 or long / short > MAX_ASPECT_RATIO:
            return None
        if expected_area_m2:
            ratio = (w_m * d_m) / expected_area_m2
            if not (AREA_MIN_MULTIPLE <= ratio <= AREA_MAX_MULTIPLE):
                return None

        box = (
            min(min(sg.x0, sg.x1) for sg in segs),
            min(min(sg.y0, sg.y1) for sg in segs),
            max(max(sg.x0, sg.x1) for sg in segs),
            max(max(sg.y0, sg.y1) for sg in segs),
        )
        errs = [
            e
            for e in (
                _closest_chain_match(w_m, chain_totals + overall_m(box, True)),
                _closest_chain_match(d_m, chain_totals + overall_m(box, False)),
            )
            if e is not None
        ]
        if not errs:
            return None
        agreement = max(errs)
        basis = ["vector_path", "dim_text"]
        if expected_area_m2:
            basis.append("floor_area")
        fp = Footprint(
            width_m=round(w_m, 3),
            depth_m=round(d_m, 3),
            basis=basis,
            agreement_pct=round(agreement, 2),
            stroke_width=width,
            n_segments=len(segs),
            bbox=box,
        )
        # Rank by dimension agreement first, then by how close the area is to
        # the expected floor area per storey, then toward the heavier line --
        # the section cut through the walls.
        #
        # Area RANKS rather than filters. Filtering on it rejected every
        # rowhouse and stacked townhouse, because for those typologies the
        # Building Performance Report describes ONE UNIT while the drawing
        # shows the whole block (RESEARCH S18), so the expected area is a
        # multiple out. As a ranking term it still separates a 170 m2 sheet
        # artefact from a 61 m2 ADU without discarding a correct footprint.
        area_err = (
            abs(w_m * d_m - expected_area_m2) / expected_area_m2 if expected_area_m2 else 0.0
        )
        # A COMBINED score, not a lexicographic one: ranking by agreement
        # first made the area term a tie-break only, which never fires, since
        # two lineweight groups rarely agree to the same decimal.
        score = (agreement + AREA_WEIGHT * area_err, -width)
        return score, fp

    best: tuple[tuple[float, float], Footprint] | None = None
    for width, segs in groups.items():
        ranked = rank(width, segs)
        if ranked and (best is None or ranked[0] < best[0]):
            best = ranked

    # Then each separate drawing in a group: a US plan sheet draws the main
    # plan beside option vignettes in one wall stroke. Clustering runs on every
    # segment of that width, short ones included, because the short corner
    # pieces are what join a plan's long wall runs. A drawing may only refine
    # the winning lineweight or a heavier one: a lighter group's cluster
    # displaced the wall cut on CMHC sheets at the same size, and the
    # partitions read walls at the footprint's stroke. Never width 0 (pochΓ©).
    floor = best[1].stroke_width or 0.0 if best else 0.0
    for width in (w for w in groups if w > 0 and w >= floor):
        parts = _clusters([sg for sg in all_segs if sg.width == width], CLUSTER_GAP_MM / s)
        # Only the largest drawing: the main plan outweighs its vignettes, and
        # offering every small cluster let a stair or a unit match some chain.
        runs = max(
            ([sg for sg in part if sg.length_mm >= MIN_SEGMENT_MM] for part in parts), key=len
        )
        if len(runs) < len(groups[width]):
            ranked = rank(width, runs)
            if ranked and (best is None or ranked[0] < best[0]):
                best = ranked

    if best is None or not best[1].confident:
        return best[1] if best else None
    return best[1]
