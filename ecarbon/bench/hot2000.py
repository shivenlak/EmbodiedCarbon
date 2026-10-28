"""STEP 9 -- envelope areas from the HOT2000 energy model.

`.h2k` files are plain XML (HOT2000 v11.13), so this needs no third-party
library. They give us a SECOND independent measurement of the same building,
made by the energy modeller rather than the architect -- which matters more
than it sounds, because the gap between two professional conventions is the
error term we cannot otherwise see (RESEARCH.md S16).

Cross-check on AB_Fourplex_01, against the IFC:

    HOT2000 tall wall records   290.6 m2   vs  IFC W2 envelope   287.6   (1.0%)
    HOT2000 short wall records   63.5 m2   vs  IFC N1 foundation  62.1   (2.2%)
    HOT2000 total              354.0 m2   vs  IFC total         349.7   (1.2%)

Two conventions worth knowing:

1. A `<Wall>` record has NO `area` attribute. It carries `height` and
   `perimeter`, so area is their product. `<Ceiling>` does carry `area`.
   Looking for `area` on a wall silently yields zero.

2. HOT2000 `<Wall>` records cover BOTH the above-grade envelope and the
   foundation wall, lumped together. They separate cleanly by height -- the
   above-grade storeys are ~2.5-2.7 m while foundation segments are under
   1.5 m -- which is how the two sets above were matched to W2 and N1.

These are THERMAL ENVELOPE areas: gross, by orientation, exterior only. There
are no interior partitions and no structural quantities, so this validates the
two biggest envelope quantities and nothing else.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Above this height a wall record is an above-grade storey; below it, a
# foundation or rim-joist segment. Calibrated on AB_Fourplex_01, where the
# split is unambiguous (2.515/2.667 m against 0.305/1.238/1.295 m).
ABOVE_GRADE_MIN_HEIGHT_M = 1.8


@dataclass
class Surface:
    kind: str
    label: str
    area_m2: float
    height_m: float | None = None
    perimeter_m: float | None = None
    r_value: float | None = None
    nominal_insulation: float | None = None
    facing: str | None = None

    @property
    def is_above_grade(self) -> bool:
        return self.height_m is None or self.height_m >= ABOVE_GRADE_MIN_HEIGHT_M


@dataclass
class Hot2000:
    source: str
    surfaces: list[Surface] = field(default_factory=list)
    n_windows: int = 0
    window_area_m2: float = 0.0
    n_doors: int = 0
    door_area_m2: float = 0.0
    slab_perimeter_m: float = 0.0
    ui_units: str = ""

    def _sum(self, kind: str, above_grade: bool | None = None) -> float:
        return sum(
            s.area_m2
            for s in self.surfaces
            if s.kind == kind and (above_grade is None or s.is_above_grade == above_grade)
        )

    @property
    def wall_area_m2(self) -> float:
        """All wall records: above-grade envelope plus foundation."""
        return self._sum("Wall")

    @property
    def above_grade_wall_area_m2(self) -> float:
        """Comparable with the IFC's W* exterior envelope tags."""
        return self._sum("Wall", above_grade=True)

    @property
    def foundation_wall_area_m2(self) -> float:
        """Comparable with the IFC's N* foundation tags."""
        return self._sum("Wall", above_grade=False)

    @property
    def ceiling_area_m2(self) -> float:
        """Comparable with the IFC's roof assembly area."""
        return self._sum("Ceiling")

    @property
    def floor_area_m2(self) -> float:
        return self._sum("Floor")

    def r_values(self) -> dict[str, float]:
        """Area-weighted mean RSI per surface kind, for assembly cross-checks."""
        out: dict[str, float] = {}
        for kind in {s.kind for s in self.surfaces}:
            rows = [s for s in self.surfaces if s.kind == kind and s.r_value and s.area_m2]
            total = sum(s.area_m2 for s in rows)
            if total:
                out[kind] = sum(s.r_value * s.area_m2 for s in rows) / total
        return out


def _f(node, attr: str) -> float | None:
    if node is None:
        return None
    v = node.get(attr)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _label(node) -> str:
    el = node.find("Label")
    return (el.text or "").strip() if el is not None and el.text else ""


@lru_cache(maxsize=32)
def parse_hot2000(path: str | Path) -> Hot2000:
    root = ET.parse(str(path)).getroot()
    out = Hot2000(source=str(path), ui_units=root.get("uiUnits", ""))

    for kind in ("Wall", "Ceiling", "Floor"):
        for node in root.iter(kind):
            meas = node.find("Measurements")
            if meas is None:
                continue
            area = _f(meas, "area")
            height = _f(meas, "height")
            perimeter = _f(meas, "perimeter")
            if area is None:
                # Walls carry height and perimeter instead of area.
                if height is None or perimeter is None:
                    continue
                area = height * perimeter
            ctype = node.find("Construction/Type")
            if ctype is None:
                ctype = node.find("Construction/CeilingType")
            facing = node.find("FacingDirection/English")
            out.surfaces.append(
                Surface(
                    kind=kind,
                    label=_label(node),
                    area_m2=area,
                    height_m=height,
                    perimeter_m=perimeter,
                    r_value=_f(ctype, "rValue"),
                    nominal_insulation=_f(ctype, "nominalInsulation"),
                    facing=(facing.text or "").strip() if facing is not None and facing.text else None,
                )
            )

    for node in root.iter("Window"):
        meas = node.find("Measurements")
        w, h = _f(meas, "width"), _f(meas, "height")
        n = int(float(node.get("number") or 1))
        out.n_windows += n
        if w and h:
            # HOT2000 window dimensions are millimetres.
            out.window_area_m2 += n * (w / 1000.0) * (h / 1000.0)

    for node in root.iter("Door"):
        meas = node.find("Measurements")
        w, h = _f(meas, "width"), _f(meas, "height")
        out.n_doors += 1
        if w and h:
            # Door dimensions are metres in this schema.
            out.door_area_m2 += w * h

    for node in root.iter("Slab"):
        p = _f(node, "exposedSurfacePerimeter")
        if p:
            out.slab_perimeter_m += p

    return out
