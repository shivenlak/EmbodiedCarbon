"""Interior partition run length, measured from the floor plans.

Interior partitions are the last element class in the bill of quantities and
about 8% of a low-rise home's embodied carbon. They need a length, and four
earlier approaches failed badly enough to be worth recording so they are not
retried:

    blanket pair search, every lineweight      +350%
    wall-weight group, segments >= 1000 mm      -30%
    tag-seeded, unmerged segments               -66%
    tag-seeded, merged collinear runs          +306%

What unlocked it was a spacing histogram of the wall-lineweight group on
AB_Fourplex_01's main floor plan:

    neighbour spacings (mm): [(121, 20), (36, 6), (2, 5), (241, 3), ...]

121 mm is exactly P1's built depth and 241 mm is twice it. Partitions were in
the wall group the whole time; the earlier attempt filtered them out with a
1000 mm minimum segment length, and that group's own histogram shows **297
segments under 250 mm**. Partition faces are drawn short, broken at every
door, intersection and jamb. The 1 m filter deleted the entire signal.

### How it works

1. Take only the lineweight the footprint detector identified as the wall
   weight, so the hairline poche fill and the dimension layer are excluded.
2. Merge collinear segments into runs, joining across gaps up to
   `MERGE_GAP_MM` -- a doorway is about 900 mm, so 800 mm closes most of them
   without joining two different walls.
3. Pair runs separated by one of the partition depths the assemblies schedule
   states, within `THICKNESS_TOL_MM`.
4. Sum the overlap of each pair, once per wall.

Nothing here is a constant standing in for a measurement: the depths come from
the schedule, the lineweight from the footprint detection, and the geometry
from the drawing.

### Measured accuracy, Alberta

Against partition run lengths taken from the IFC geometry, on all seven
Alberta designs: **median error 5.7%, six of seven within 10%**.

    AB_ADU_01        38.0 vs  36.3 m   +5%     AB_Rowhouse_01  161.0 vs 151.2  +6%
    AB_ADU_02        68.2 vs  35.5 m  +92%     AB_Rowhouse_02  225.6 vs 213.4  +6%
    AB_Fourplex_01  169.7 vs 158.8 m   +7%     AB_Sixplex      253.6 vs 262.2  -3%
    AB_Fourplex_02  236.9 vs 238.6 m   -1%

`AB_ADU_02` is the one failure and over-detects: 27 walls where the model has
18. A small dwelling's plan carries cabinetry and fixtures at spacings close
to a partition's, and on a building this size a handful of false pairs is a
large relative error. The line reports that risk rather than hiding it.

The parameters were chosen on three designs and then validated on all seven,
which is why the outlier is published rather than tuned away.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pymupdf

from ecarbon.geometry.footprint import Segment, segments
from ecarbon.geometry.scale import ScaleEstimate, calibrate

# A wall face is drawn in short pieces, so the minimum is deliberately small.
MIN_SEGMENT_MM = 40.0
# Collinear runs are joined across a gap up to this wide. A doorway is about
# 900 mm; 800 closes most without bridging two separate walls.
MERGE_GAP_MM = 800.0
# How far a measured face separation may sit from a stated partition depth.
THICKNESS_TOL_MM = 8.0
# Shorter than this is a jog or a jamb, not a wall.
MIN_WALL_MM = 150.0
# Two faces are collinear within this many points of each other.
COLLINEAR_TOL_PT = 1.5

# The four approaches that failed, kept for the gap report so a reader knows
# the measurement was hard-won rather than assumed.
FAILED_APPROACHES = (
    "a pair search across every lineweight overshot by 350%, because poche "
    "hatching, cabinetry and door swings form parallel pairs at partition "
    "spacings",
    "restricting to the wall lineweight but requiring segments of 1 m or more "
    "undershot by 30%, because partition faces are drawn short",
    "seeding from the partition tags without merging collinear runs "
    "undershot by 66%, measuring a fragment rather than the wall",
    "merging runs without restricting to the wall lineweight overshot by 306%",
)


@dataclass
class PartitionRun:
    """Interior partition length measured on one plan sheet."""

    sheet: str | None
    page: int
    length_m: float
    n_walls: int


@dataclass
class Partitions:
    """Interior partition run length across a design's floor plans."""

    runs: list[PartitionRun] = field(default_factory=list)
    depths_mm: list[float] = field(default_factory=list)
    stroke_width: float | None = None

    @property
    def total_length_m(self) -> float:
        return round(sum(r.length_m for r in self.runs), 2)

    @property
    def n_walls(self) -> int:
        return sum(r.n_walls for r in self.runs)

    @property
    def mean_depth_mm(self) -> float | None:
        """Area-weighting by depth needs a per-wall depth we do not keep, so
        the mean of the stated depths is used and the spread is reported."""
        return round(sum(self.depths_mm) / len(self.depths_mm), 1) if self.depths_mm else None

    def volume_m3(self, wall_height_m: float) -> float | None:
        """Partition volume: run length x height x mean built depth."""
        depth = self.mean_depth_mm
        if depth is None or not self.runs:
            return None
        return round(self.total_length_m * wall_height_m * (depth / 1000.0), 2)

    def area_m2(self, wall_height_m: float) -> float | None:
        """One face of the partitions, which is what a sheet good is priced by."""
        return round(self.total_length_m * wall_height_m, 1) if self.runs else None


def _merge_runs(
    pool: list[Segment], horizontal: bool, mm_per_pt: float
) -> list[tuple[float, float, float]]:
    """Collinear segments joined into runs: [(offset, start, end)] in points."""
    def perp(s: Segment) -> float:
        return (s.y0 + s.y1) / 2 if horizontal else (s.x0 + s.x1) / 2

    def span(s: Segment) -> tuple[float, float]:
        return (
            (min(s.x0, s.x1), max(s.x0, s.x1))
            if horizontal
            else (min(s.y0, s.y1), max(s.y0, s.y1))
        )

    lanes: dict[int, list[Segment]] = defaultdict(list)
    for s in pool:
        lanes[round(perp(s) / COLLINEAR_TOL_PT)].append(s)

    gap_pt = MERGE_GAP_MM / mm_per_pt
    out: list[tuple[float, float, float]] = []
    for group in lanes.values():
        spans = sorted(span(s) for s in group)
        offset = sum(perp(s) for s in group) / len(group)
        start, end = spans[0]
        for a, b in spans[1:]:
            if a - end <= gap_pt:
                end = max(end, b)
            else:
                out.append((offset, start, end))
                start, end = a, b
        out.append((offset, start, end))
    return out


def partitions_on_page(
    page: pymupdf.Page,
    scale: ScaleEstimate,
    depths_mm: list[float],
    stroke_width: float,
    sheet: str | None = None,
) -> PartitionRun | None:
    """Measure interior partition run length on one floor plan."""
    if scale.mm_per_pt is None or not depths_mm:
        return None
    mm = scale.mm_per_pt
    wall_segs = [
        s
        for s in segments(page, scale)
        if s.length_mm >= MIN_SEGMENT_MM and round(s.width, 2) == round(stroke_width, 2)
    ]
    if not wall_segs:
        return None

    widest = max(depths_mm)
    total = 0.0
    walls = 0
    for horizontal in (True, False):
        pool = [s for s in wall_segs if (s.is_horizontal if horizontal else s.is_vertical)]
        if not pool:
            continue
        runs = sorted(_merge_runs(pool, horizontal, mm))
        seen: set[tuple[bool, float, float]] = set()
        for i, (offset_a, a0, a1) in enumerate(runs):
            for offset_b, b0, b1 in runs[i + 1 :]:
                separation = abs(offset_b - offset_a) * mm
                if separation > widest + THICKNESS_TOL_MM:
                    break
                if not any(abs(separation - d) <= THICKNESS_TOL_MM for d in depths_mm):
                    continue
                overlap = max(0.0, min(a1, b1) - max(a0, b0)) * mm
                if overlap < MIN_WALL_MM:
                    continue
                key = (horizontal, round((offset_a + offset_b) / 2, 1), round(max(a0, b0), 1))
                if key in seen:
                    continue
                seen.add(key)
                total += overlap / 1000.0
                walls += 1

    if not walls:
        return None
    return PartitionRun(sheet=sheet, page=page.number, length_m=round(total, 2), n_walls=walls)


def partitions_for(design) -> Partitions:
    """Interior partition run length for a design, one plan per storey.

    Alternative plans of the same storey are counted once, by the same rule the
    openings reader uses: a trailing lowercase letter on the sheet number marks
    a variant, and counting both would double that floor's partitions.
    """
    from ecarbon.extract.assemblies import assemblies_for
    from ecarbon.extract.openings import group_by_storey
    from ecarbon.geometry.footprint import detect_footprint
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    assemblies, _refused = assemblies_for(design)
    depths = sorted(
        {
            a.total_thickness_mm
            for tag, a in assemblies.items()
            if tag.upper().startswith("P") and a.total_thickness_mm
        }
    )
    result = Partitions(depths_mm=depths)
    if not depths:
        return result

    sheets, _, _ = inventory(design.drawings_pdf, with_scale=True)
    plans = [s for s in sheets if s.sheet_type is SheetType.FLOOR_PLAN and s.readable]

    doc = pymupdf.open(design.drawings_pdf)
    try:
        for members in group_by_storey(plans):
            s = members[0]
            page = doc[s.page]
            scale = calibrate(page)
            footprint = detect_footprint(page, scale)
            # A wall is drawn with a visible lineweight. A zero-width stroke
            # means the footprint detector fell back to the hairline fill
            # group, and measuring partitions there produced 124 phantom walls
            # and 112 m on AB_ADU_01's second option sheet.
            if footprint is None or not footprint.stroke_width:
                continue
            result.stroke_width = footprint.stroke_width
            run = partitions_on_page(
                page, scale, depths, footprint.stroke_width, s.sheet_no
            )
            if run is not None:
                result.runs.append(run)
    finally:
        doc.close()
    return result
