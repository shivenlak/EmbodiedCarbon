"""What a person stated when the drawings could not be read (contract C2).

When the pipeline cannot find a scale, a footprint or the storey heights, the
user can supply them in about thirty seconds: click both ends of a dimension
and type it, click the building's corners, or type the heights. Those inputs
arrive here and are threaded into `gather()` in place of what extraction would
have produced.

A stated input is never presented as measured. Every line built from one
carries `BasisSource.USER`, a basis note starting ``"stated: "`` (contract C3,
which the UI keys a "you said" chip off), and at most `INFERRED` confidence:
the arithmetic is ours but the input is the user's.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ecarbon.extract.levels import Level, StoreyHeights
from ecarbon.geometry.footprint import Footprint
from ecarbon.models import BasisSource, Confidence, ElementClass, TakeoffLine

# The prefix the UI reads to show that a line rests on something the user said.
STATED_PREFIX = "stated: "

# A storey outside this range is a typo, not a building.
MIN_STOREY_M = 2.0
MAX_STOREY_M = 6.0


@dataclass
class Overrides:
    """User-stated inputs, all optional. Empty means today's behaviour exactly."""

    # page index -> real millimetres per PDF point, from a dimension the user read.
    scale_mm_per_pt: dict[int, float] = field(default_factory=dict)
    # (page, polygon in PDF points) for the outside of the building.
    footprint: tuple[int, list[tuple[float, float]]] | None = None
    storey_heights_m: list[float] | None = None
    # What the user typed, kept for the line notes ("23'-6\" between two clicks").
    said: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.scale_mm_per_pt and self.footprint is None and not self.storey_heights_m

    def to_dict(self) -> dict:
        return {
            "scale_mm_per_pt": {str(k): v for k, v in self.scale_mm_per_pt.items()},
            "footprint": (
                None if self.footprint is None
                else {"page": self.footprint[0], "corners": [list(c) for c in self.footprint[1]]}
            ),
            "storey_heights_m": self.storey_heights_m,
            "said": dict(self.said),
        }


# -- reading what the user typed -------------------------------------------

_METRIC_UNIT_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*$", re.I)


def parse_length_mm(value: str | float | int) -> float:
    """A length as the user typed it, in millimetres.

    Accepts a bare number (millimetres, the drafting convention; a value
    under 100 is read as metres, since nobody dimensions a building in
    fractions of a metre of millimetres), `7.16 m`, `716 cm`, `7160 mm`, and
    feet-and-inches such as `23'-6"` or `23' 6 1/2"`.
    """
    if isinstance(value, (int, float)):
        v = float(value)
        return v * 1000.0 if v < 100 else v
    text = str(value).strip()
    m = _METRIC_UNIT_RE.match(text)
    if m:
        v = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        if unit == "m" or (not unit and v < 100):
            return v * 1000.0
        if unit == "cm":
            return v * 10.0
        return v
    from ecarbon.geometry.scale import parse_imperial

    mm = parse_imperial(text.replace("’", "'").replace("”", '"'))
    if mm is None:
        raise ValueError(f"could not read {value!r} as a length")
    return mm


def scale_from_points(
    p1: tuple[float, float], p2: tuple[float, float], length_mm: float
) -> float:
    """Millimetres per PDF point, from two clicked points a known length apart."""
    pts = math.dist(p1, p2)
    if pts < 5.0:
        raise ValueError("the two points are too close together to set a scale")
    if length_mm <= 0:
        raise ValueError("the length must be positive")
    return length_mm / pts


# -- stated stand-ins for what extraction produces ---------------------------


@dataclass
class StatedFootprint(Footprint):
    """A footprint the user traced. Area and perimeter come from the polygon,
    so an L-shaped plan is measured as drawn rather than as its bounding box."""

    polygon_area_m2: float = 0.0
    polygon_perimeter_m: float = 0.0

    @property
    def area_m2(self) -> float:  # type: ignore[override]
        return self.polygon_area_m2

    @property
    def perimeter_m(self) -> float:  # type: ignore[override]
        return self.polygon_perimeter_m

    @property
    def confident(self) -> bool:  # type: ignore[override]
        # Not corroborated by a second source, but it is what the person
        # looking at the drawing said; extraction must not override it.
        return True


def footprint_from_polygon(
    corners: list[tuple[float, float]], mm_per_pt: float
) -> StatedFootprint:
    if len(corners) < 3:
        raise ValueError("a footprint needs at least three corners")
    m = mm_per_pt / 1000.0
    pts = [(x * m, y * m) for x, y in corners]
    area = 0.0
    perim = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        area += x0 * y1 - x1 * y0
        perim += math.dist((x0, y0), (x1, y1))
    area = abs(area) / 2.0
    if area < 4.0:
        raise ValueError(f"the traced footprint is only {area:.1f} m2; check the scale")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return StatedFootprint(
        width_m=round(max(xs) - min(xs), 3),
        depth_m=round(max(ys) - min(ys), 3),
        basis=["stated by the user (traced corners)"],
        agreement_pct=None,
        polygon_area_m2=round(area, 2),
        polygon_perimeter_m=round(perim, 2),
        n_segments=len(corners),
    )


class StatedStoreyHeights(StoreyHeights):
    """Storey heights the user typed, one per storey, lowest first."""

    def __init__(self, heights_m: list[float], floor_assembly_mm: float | None = None):
        clean = [float(h) for h in heights_m]
        for h in clean:
            if not (MIN_STOREY_M <= h <= MAX_STOREY_M):
                raise ValueError(
                    f"a storey of {h:.2f} m is outside {MIN_STOREY_M}-{MAX_STOREY_M} m"
                )
        elevations = [0.0]
        for h in clean[:-1]:
            elevations.append(elevations[-1] + h)
        super().__init__(
            levels=[
                Level(label=f"STATED FLOOR {i + 1}", elevation_m=round(e, 3))
                for i, e in enumerate(elevations)
            ],
            floor_assembly_mm=floor_assembly_mm,
            sources=[],
            notes=[
                "Storey heights stated by the user: "
                + ", ".join(f"{h:.2f} m" for h in clean)
                + "."
            ],
        )
        self._stated = clean

    def storey_heights_m(self) -> list[float]:
        return list(self._stated)


# -- labelling ---------------------------------------------------------------

# Which lines rest on which stated input. A scale is only ever used to find
# the footprint, so it reaches the same lines a stated footprint does.
_FROM_FOOTPRINT = {
    ElementClass.SLAB_ON_GRADE,
    ElementClass.FOOTING,
    ElementClass.FOUNDATION_WALL,
    ElementClass.EXTERIOR_WALL,
    ElementClass.ROOF_ASSEMBLY,
    ElementClass.FLOOR_ASSEMBLY,
    ElementClass.INSULATION,
    ElementClass.CLADDING,
}
_FROM_HEIGHTS = {
    ElementClass.EXTERIOR_WALL,
    ElementClass.INTERIOR_PARTITION,
    ElementClass.PARTY_WALL,
    ElementClass.INSULATION,
    ElementClass.CLADDING,
}


def label_stated(lines: list[TakeoffLine], overrides: Overrides | None) -> None:
    """Mark every line that rests on a stated input, in place."""
    if overrides is None or overrides.empty:
        return
    said = []
    classes: set[ElementClass] = set()
    if overrides.footprint is not None:
        said.append(overrides.said.get("footprint", "the building outline you traced"))
        classes |= _FROM_FOOTPRINT
    elif overrides.scale_mm_per_pt:
        said.append(overrides.said.get("scale", "the scale you set"))
        classes |= _FROM_FOOTPRINT
    if overrides.storey_heights_m:
        said.append(overrides.said.get("heights", "the storey heights you typed"))
        classes |= _FROM_HEIGHTS
    what = "; ".join(said)
    for line in lines:
        if line.element_class not in classes or line.quantity == 0:
            continue
        sources = list(line.basis.sources)
        if BasisSource.USER not in sources:
            sources.append(BasisSource.USER)
        rest = line.basis.note or ""
        line.basis = line.basis.model_copy(
            update={"sources": sources, "note": f"{STATED_PREFIX}{what}. {rest}".strip()}
        )
        if line.confidence is Confidence.MEASURED:
            line.confidence = Confidence.INFERRED
