"""Ground truth from the IFC model.

Used for scoring only -- the pipeline never reads the IFC during extraction,
because Landmark's plan sets are PDF and a benchmark that peeks at the answer
measures nothing.

As discovered in RESEARCH.md §5:
  - 52 of 53 IFCs contain zero IfcElementQuantity or pre-computed volumes.
  - All SKMB designs (Vectorworks export) lack semantic element classes
    (zero IfcWall/IfcSlab/IfcWindow).
  - NOR Tanked designs contain 650-812 IfcSlabs with zero footings.
  - Slabs in catalogue models contain landscape elements (asphalt, grass)
    that must be filtered out by `is_site_element`.

This engine derives exact 3D volumes and surface areas directly from IFC geometry
and resolves IfcMaterialLayerSetUsage to yield material-by-material quantities.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

# Name fragments that mark an element as site/landscape rather than building.
SITE_MARKERS = ("xsite", "site -", "topography", "landscape", "asphalt", "grass", "paver")

BUILDING_WALL_TYPES = ("IfcWall", "IfcWallStandardCase")


def is_site_element(name: str | None) -> bool:
    low = (name or "").lower()
    return any(m in low for m in SITE_MARKERS)


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


@dataclass(frozen=True)
class IFCLayerInfo:
    material_name: str
    thickness_mm: float
    volume_m3: float


@dataclass(frozen=True)
class IFCElementRecord:
    element_id: int
    element_type: str
    name: str
    volume_m3: float
    thickness_m: float | None = None
    area_m2: float | None = None
    is_exterior: bool = False
    assembly_tag: str | None = None
    layers: list[IFCLayerInfo] = field(default_factory=list)


@dataclass(frozen=True)
class IFCTakeoffTruth:
    file_path: Path
    is_usable: bool
    unusable_reason: str | None

    # Extents
    bbox: BBox | None = None

    # Aggregated quantities (building only, excluding site)
    exterior_wall_area_m2: float = 0.0
    exterior_wall_volume_m3: float = 0.0
    slab_on_grade_volume_m3: float = 0.0
    slab_on_grade_area_m2: float = 0.0
    upper_floor_slab_volume_m3: float = 0.0
    roof_volume_m3: float = 0.0
    footing_volume_m3: float = 0.0
    window_count: int = 0
    door_count: int = 0

    # Material volumes: material name -> m3
    material_volumes_m3: dict[str, float] = field(default_factory=dict)

    # Detailed element records
    elements: list[IFCElementRecord] = field(default_factory=list)


def _compute_mesh_volume(verts_flat: list[float], faces_flat: list[int]) -> float:
    """Compute volume of closed 3D triangular mesh via divergence theorem."""
    import numpy as np

    if not verts_flat or not faces_flat:
        return 0.0
    verts = np.array(verts_flat, dtype=np.float64).reshape(-1, 3)
    faces = np.array(faces_flat, dtype=np.int64).reshape(-1, 3)
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    signed_vols = np.sum(v0 * cross, axis=1) / 6.0
    return float(np.abs(np.sum(signed_vols)))


def _extract_assembly_tag(name: str | None) -> str | None:
    """Extract assembly code like 'W2', 'P1', 'F1', 'R1' from element or type name."""
    import re

    if not name:
        return None
    m = re.search(r"\b([WPFSRC][0-9]{1,2})\b", name)
    return m.group(1) if m else None


@lru_cache(maxsize=16)
def building_bbox(ifc_path: str | Path, types: tuple[str, ...] = BUILDING_WALL_TYPES) -> BBox | None:
    """Extent of the building envelope, excluding site elements."""
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
    return BBox(
        x_mm=(hi[0] - lo[0]) * 1000.0,
        y_mm=(hi[1] - lo[1]) * 1000.0,
        z_mm=(hi[2] - lo[2]) * 1000.0,
        n_shapes=n,
    )


def parse_ifc_takeoff(ifc_path: str | Path) -> IFCTakeoffTruth:
    """Extract ground truth element and material quantities from an IFC model."""
    import ifcopenshell
    import ifcopenshell.geom as geom

    path = Path(ifc_path)
    model = ifcopenshell.open(str(path))

    # Usability checks per RESEARCH.md §5:
    # 1. Vectorworks SKMB files lack semantic classes
    all_walls = model.by_type("IfcWall")
    all_slabs = model.by_type("IfcSlab")
    if not all_walls and not all_slabs:
        return IFCTakeoffTruth(
            file_path=path,
            is_usable=False,
            unusable_reason="vectorworks_brep_no_semantic_elements (SKMB design)",
        )

    # 2. NOR Tanked variants have >500 slabs and 0 footings
    all_footings = model.by_type("IfcFooting")
    if len(all_slabs) > 500 and not all_footings:
        return IFCTakeoffTruth(
            file_path=path,
            is_usable=False,
            unusable_reason="nor_tanked_inconsistent_slabs (650+ slabs, 0 footings)",
        )

    settings = geom.settings()
    settings.set("use-world-coords", True)

    # Map object id -> list of (material_name, thickness_mm)
    element_layer_map: dict[int, list[tuple[str, float]]] = {}
    for rel in model.by_type("IfcRelAssociatesMaterial"):
        mat = rel.RelatingMaterial
        layers: list[tuple[str, float]] = []
        if mat.is_a("IfcMaterialLayerSetUsage"):
            ls = mat.ForLayerSet
            for l in ls.MaterialLayers:
                mname = l.Material.Name if l.Material else "Unknown"
                layers.append((mname, float(l.LayerThickness)))
        elif mat.is_a("IfcMaterialLayerSet"):
            for l in mat.MaterialLayers:
                mname = l.Material.Name if l.Material else "Unknown"
                layers.append((mname, float(l.LayerThickness)))
        elif mat.is_a("IfcMaterial"):
            layers.append((mat.Name, 0.0))

        if layers:
            for obj in rel.RelatedObjects:
                element_layer_map[obj.id()] = layers

    bbox = building_bbox(path)
    element_records: list[IFCElementRecord] = []
    material_vols: dict[str, float] = defaultdict(float)

    total_ext_wall_area = 0.0
    total_ext_wall_vol = 0.0
    total_sog_vol = 0.0
    total_sog_area = 0.0
    total_upper_slab_vol = 0.0
    total_roof_vol = 0.0
    total_footing_vol = 0.0

    target_types = ("IfcWall", "IfcSlab", "IfcRoof", "IfcFooting")
    for tname in target_types:
        for el in model.by_type(tname):
            el_name = getattr(el, "Name", "") or ""
            if is_site_element(el_name):
                continue

            try:
                shape = geom.create_shape(settings, el)
            except Exception:
                continue

            vol = _compute_mesh_volume(shape.geometry.verts, shape.geometry.faces)
            if vol <= 0.0001:
                continue

            layers = element_layer_map.get(el.id(), [])
            tot_thickness_mm = sum(th for _, th in layers)
            thickness_m = tot_thickness_mm / 1000.0 if tot_thickness_mm > 0 else None
            area_m2 = (vol / thickness_m) if (thickness_m and thickness_m > 0) else None

            # Distribute layer volumes
            layer_infos: list[IFCLayerInfo] = []
            if layers and tot_thickness_mm > 0:
                for mname, th_mm in layers:
                    frac = th_mm / tot_thickness_mm
                    l_vol = vol * frac
                    material_vols[mname] += l_vol
                    layer_infos.append(
                        IFCLayerInfo(material_name=mname, thickness_mm=th_mm, volume_m3=round(l_vol, 4))
                    )
            elif layers:
                for mname, _ in layers:
                    material_vols[mname] += vol
                    layer_infos.append(
                        IFCLayerInfo(material_name=mname, thickness_mm=0.0, volume_m3=round(vol, 4))
                    )
            else:
                material_vols[f"Unknown:{tname}"] += vol

            tag = _extract_assembly_tag(el_name)
            is_ext = False
            up_name = el_name.upper()

            if tname == "IfcWall":
                is_ext = any(k in up_name for k in ("EXTERIOR", "W1", "W2", "EW-", "EXT_"))
                if is_ext:
                    total_ext_wall_vol += vol
                    if area_m2 is not None:
                        total_ext_wall_area += area_m2
                    else:
                        # Fallback thickness 240mm if not layered
                        total_ext_wall_area += vol / 0.24

            elif tname == "IfcSlab":
                if any(k in up_name for k in ("F1", "SLAB ON GRADE", "GRADE")):
                    total_sog_vol += vol
                    if area_m2 is not None:
                        total_sog_area += area_m2
                    else:
                        total_sog_area += vol / 0.15
                elif any(k in up_name for k in ("ROOF", "R1", "R2")):
                    total_roof_vol += vol
                else:
                    total_upper_slab_vol += vol

            elif tname == "IfcRoof":
                total_roof_vol += vol

            elif tname == "IfcFooting":
                total_footing_vol += vol

            element_records.append(
                IFCElementRecord(
                    element_id=el.id(),
                    element_type=tname,
                    name=el_name,
                    volume_m3=round(vol, 4),
                    thickness_m=round(thickness_m, 4) if thickness_m else None,
                    area_m2=round(area_m2, 4) if area_m2 else None,
                    is_exterior=is_ext,
                    assembly_tag=tag,
                    layers=layer_infos,
                )
            )

    windows = model.by_type("IfcWindow")
    doors = model.by_type("IfcDoor")

    return IFCTakeoffTruth(
        file_path=path,
        is_usable=True,
        unusable_reason=None,
        bbox=bbox,
        exterior_wall_area_m2=round(total_ext_wall_area, 2),
        exterior_wall_volume_m3=round(total_ext_wall_vol, 2),
        slab_on_grade_volume_m3=round(total_sog_vol, 2),
        slab_on_grade_area_m2=round(total_sog_area, 2),
        upper_floor_slab_volume_m3=round(total_upper_slab_vol, 2),
        roof_volume_m3=round(total_roof_vol, 2),
        footing_volume_m3=round(total_footing_vol, 2),
        window_count=len(windows),
        door_count=len(doors),
        material_volumes_m3={k: round(v, 3) for k, v in material_vols.items()},
        elements=element_records,
    )
