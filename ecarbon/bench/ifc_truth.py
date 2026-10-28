"""Ground truth from the IFC model.

Used for scoring only -- the pipeline never reads the IFC, because Landmark's
plan sets are PDF and a benchmark that peeks at the answer measures nothing.

Two things to know before trusting a model:

1. LANDSCAPE elements are modelled as IfcSlab -- `Floor:xSite - Asphalt`,
   `Floor:xSite - Grass`. They are not part of the building and must be
   excluded from any takeoff too, or the model gains hundreds of square metres
   of fictitious asphalt. On AB_Fourplex_01, including them inflates the
   footprint from 7.0 x 22.0 m to 31.2 x 46.3 m. CMHC appears to prefix
   non-building families with 'x'.

2. GEOMETRY COVERAGE varies. All 53 models carry correct semantic elements, but
   the 7 Vectorworks (SKMB) exports use B-rep geometry that IfcOpenShell can
   only partly build -- 0% to 74% of walls yield a shape, versus 100% for the
   46 Revit exports. A model can therefore have the right element count and
   still be useless for quantities, which `geometry_coverage()` detects.
   Measured 2026-10-24; see RESEARCH.md §15.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Name fragments that mark an element as site/landscape rather than building.
SITE_MARKERS = ("xsite", "site -", "topography", "landscape", "asphalt", "grass", "paver")

BUILDING_WALL_TYPES = ("IfcWall", "IfcWallStandardCase")


def is_site_element(name: str | None) -> bool:
    low = (name or "").lower()
    return any(m in low for m in SITE_MARKERS)


# Below this fraction of wall elements yielding geometry, the model cannot be
# trusted for quantities. The Vectorworks (SKMB) exports carry correct semantic
# data but B-rep geometry that IfcOpenShell can only partly build.
MIN_GEOMETRY_COVERAGE = 0.90


@dataclass(frozen=True)
class Coverage:
    """How much of the model's wall geometry can actually be built."""

    n_elements: int
    n_shapes: int

    @property
    def fraction(self) -> float:
        return self.n_shapes / self.n_elements if self.n_elements else 0.0

    @property
    def usable(self) -> bool:
        return self.fraction >= MIN_GEOMETRY_COVERAGE

    @property
    def verdict(self) -> str:
        f = self.fraction
        return "good" if f >= 0.90 else ("partial" if f >= 0.40 else "poor")


@dataclass(frozen=True)
class BBox:
    """Axis-aligned extent in millimetres."""

    x_mm: float
    y_mm: float
    z_mm: float
    n_shapes: int

    @property
    def footprint_m2(self) -> float:
        return (self.x_mm / 1000.0) * (self.y_mm / 1000.0)

    @property
    def plan_mm(self) -> tuple[float, float]:
        """(shorter, longer) plan dimension, so comparisons are orientation-free."""
        return (min(self.x_mm, self.y_mm), max(self.x_mm, self.y_mm))


@lru_cache(maxsize=16)
def building_bbox(
    ifc_path: str | Path, types: tuple[str, ...] = BUILDING_WALL_TYPES
) -> BBox | None:
    """Extent of the building envelope, excluding site elements.

    Walls are the default because they define the envelope cleanly: slabs in
    these models include landscape, and footings extend past the wall line.
    """
    import ifcopenshell
    import ifcopenshell.geom as geom

    model = ifcopenshell.open(str(ifc_path))
    settings = geom.settings()
    settings.set("use-world-coords", True)

    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    n = 0
    for t in types:
        try:
            elements = model.by_type(t)
        except Exception:
            continue
        for el in elements:
            if is_site_element(getattr(el, "Name", None)):
                continue
            try:
                shape = geom.create_shape(settings, el)
            except Exception:
                continue
            verts = shape.geometry.verts
            if not verts:
                continue
            for axis in range(3):
                coords = verts[axis::3]
                if coords:
                    lo[axis] = min(lo[axis], min(coords))
                    hi[axis] = max(hi[axis], max(coords))
            n += 1

    if not n or lo[0] == float("inf"):
        return None
    # ifcopenshell returns world coordinates in metres regardless of the file's
    # own length unit, so convert once here.
    return BBox(
        x_mm=(hi[0] - lo[0]) * 1000.0,
        y_mm=(hi[1] - lo[1]) * 1000.0,
        z_mm=(hi[2] - lo[2]) * 1000.0,
        n_shapes=n,
    )


@lru_cache(maxsize=16)
def geometry_coverage(ifc_path: str | Path) -> Coverage:
    """What fraction of building walls yield buildable geometry.

    This is the gate for using a model as quantity ground truth. Element counts
    alone are misleading: SKMB_ADU_02 declares 22 walls and builds 0 shapes.
    """
    import ifcopenshell
    import ifcopenshell.geom as geom

    model = ifcopenshell.open(str(ifc_path))
    settings = geom.settings()
    settings.set("use-world-coords", True)

    elements = [
        el
        for t in BUILDING_WALL_TYPES
        for el in model.by_type(t)
        if not is_site_element(getattr(el, "Name", None))
    ]
    built = 0
    for el in elements:
        try:
            if geom.create_shape(settings, el).geometry.verts:
                built += 1
        except Exception:
            continue
    return Coverage(n_elements=len(elements), n_shapes=built)
