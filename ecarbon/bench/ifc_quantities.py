"""STEP 9 -- quantities from the IFC model, for scoring the PDF takeoff.

Scoring only. The pipeline never reads the IFC; Landmark's sets are PDF, and a
benchmark that peeks at the answer measures nothing.

### How area is derived

Not from face areas. A mesh's surface area counts both faces plus the edges,
and picking "the wall face" out of a triangle soup is fragile. Instead:

    area = volume / total_layer_thickness

The volume comes from the mesh (signed tetrahedron sum, exact for a closed
mesh) and the thickness from the element's `IfcMaterialLayerSet`, which is
authoritative. For a layered prismatic element the division is exact, and it
falls out that per-layer volume is simply `area * layer_thickness`.

### Three things the catalogue models require

1. `by_type("IfcWall")` ALREADY INCLUDES `IfcWallStandardCase`, which is a
   subtype. Adding the two double-counts -- AB_Fourplex_01 has 92 walls, not
   the 166 that summing them suggests.

2. 18 of those 92 walls carry NO material association at all, 9 of them
   exterior envelope. Their build-up is recovered from other walls sharing the
   same assembly tag (`W2`, `P1`, `N1` ...), since walls of one tag share a
   build-up by definition. Such quantities are flagged `thickness_inferred`,
   which is the measured/inferred distinction the scope requires, applied to
   our own ground truth.

3. Openings are NOT cut from the exterior wall geometry in these models: W2
   measures 287.3 m2 net against 287.6 gross, while interior P1 walls do show
   door voids (198.1 vs 259.0). So an exterior wall figure from geometry alone
   is a GROSS area, and net-of-openings has to come from subtracting the
   window and door schedule explicitly. Both are reported, because which one
   a reference takeoff uses is a convention we cannot see in advance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ecarbon.bench.ifc_truth import is_site_element

# Element types we quantify, and the IFC type that carries each.
WALL_TYPES = ("IfcWall",)  # includes IfcWallStandardCase
SLAB_TYPES = ("IfcSlab",)
FOOTING_TYPES = ("IfcFooting",)
ROOF_TYPES = ("IfcRoof",)
OPENING_TYPES = ("IfcWindow", "IfcDoor")


def _mesh_volume(shape) -> float:
    """Volume of a closed triangle mesh, in m3 (world coords are metres)."""
    import numpy as np

    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
    if not len(faces):
        return 0.0
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0))


def assembly_tag(name: str | None) -> str:
    """'Basic Wall:W2 -RATED EXTERIOR ENVELOPE WALL:6595017' -> 'W2 -RATED...'.

    The middle segment is the Revit type name, and it is the same tag that
    appears on the drawings' sections and in the A003 assemblies schedule --
    which is what makes IFC quantities comparable with a PDF takeoff at all.
    """
    if not name:
        return "?"
    parts = name.split(":")
    return parts[1].strip() if len(parts) > 1 else name.strip()


# Words that make a wall interior no matter what else the tag says. A demising
# or party wall separates units; cladding applied to BOTH sides means the wall
# has no outdoor face.
_INTERIOR_OVERRIDE = ("DEMISING", "BOTH SIDES", "PARTY", "PLUMBING", "CHASE", "FURRING")
# Words that mark an outdoor face.
_EXTERIOR_WORDS = ("EXTERIOR", "ENVELOPE", "CLADDING", "BRICK", "SHINGLE", "SIDING", "STUCCO")


def wall_role(tag: str) -> str:
    """Classify a wall assembly tag as exterior / foundation / interior.

    Ordered precedence, not flat keyword presence -- that distinction is the
    whole difficulty. Three naming conventions had to be reconciled:

      AB  `W2 -RATED EXTERIOR ENVELOPE WALL`, `P1 - 2x4 Stud`
      AB  `CPH-2-STANDARD EXTERIOR ENVELOPE WALL`   (no W prefix at all)
      ATL `W2 - 2x6 Stud w Metal Cladding`          (envelope, but says Stud)
      ATL `W8 - RATED DEMISING`                     (W prefix, but interior)
      ATL `W9 - 2x8 Stud w Metal Cladding_(both sides)`  (clad, but interior)
      QC  `W1 - 2x6 Stud w Brick`

    A code-prefix rule returned 11 m2 of soffit bulkhead as AB_ADU_01's entire
    envelope. Replacing it with flat keywords then misread every ATL and QC
    envelope wall as interior, because they are described by their framing
    ("2x6 Stud") rather than their position -- which dropped those designs to
    0.21-0.47 of their HOT2000 wall area. Hence: foundation first, then
    interior OVERRIDES, then exterior evidence, then framing.
    """
    up = tag.upper()
    if "FOUNDATION" in up or "FOOTING" in up or re.match(r"^N\d", up):
        return "foundation"
    if any(w in up for w in _INTERIOR_OVERRIDE):
        return "interior"
    if any(w in up for w in _EXTERIOR_WORDS):
        return "exterior"
    if re.match(r"^P\d", up) or "STUD" in up or "PARTITION" in up or "RATED WALL" in up:
        return "interior"
    # A bare W code with nothing else to go on is the envelope convention.
    return "exterior" if up.startswith("W") else "interior"


def short_tag(name: str | None) -> str:
    """Just the code: 'W2 -RATED EXTERIOR ENVELOPE WALL' -> 'W2'."""
    tag = assembly_tag(name)
    head = tag.split()[0] if tag else "?"
    return head.rstrip("-,").strip() or "?"


def length_scale_to_mm(model) -> float:
    """Millimetres per unit of this file's declared length unit.

    Attribute values such as `IfcMaterialLayer.LayerThickness` are in the
    file's own units, unlike geometry read through ifcopenshell's engine with
    world coordinates, which always arrives in metres. The catalogue is not
    consistent: Alberta and Quebec declare MILLI/METRE, while **every BC model
    declares FOOT**. Reading those raw gave partition build-ups of 0.40 to
    1.20 "mm" and scored a 172 mm wall as 34,300% in error against a 0.50 ft
    layer set that is really 152.4 mm.
    """
    try:
        for assignment in model.by_type("IfcUnitAssignment"):
            for unit in assignment.Units:
                if getattr(unit, "UnitType", None) != "LENGTHUNIT":
                    continue
                if unit.is_a("IfcSIUnit"):
                    return 1.0 if unit.Prefix == "MILLI" else 1000.0
                if unit.is_a("IfcConversionBasedUnit"):
                    factor = unit.ConversionFactor
                    metres = float(factor.ValueComponent.wrappedValue)
                    base = factor.UnitComponent
                    if getattr(base, "Prefix", None) == "MILLI":
                        metres /= 1000.0
                    return metres * 1000.0
    except Exception:
        pass
    # Millimetres is the catalogue's majority convention and the IFC default
    # for Revit exports, so it is the least surprising fallback.
    return 1.0


def _model_of(element):
    for attr in ("file", "wrapped_data"):
        owner = getattr(element, attr, None)
        if owner is None:
            continue
        return getattr(owner, "file", owner)
    return None


def material_layers(element) -> list[tuple[str, float]] | None:
    """[(material name, thickness mm)] for an element, or None if unassigned.

    Thicknesses are converted to millimetres using the file's own length unit,
    which is not the same across the catalogue -- see `length_scale_to_mm`.
    """
    for rel in getattr(element, "HasAssociations", None) or []:
        if not rel.is_a("IfcRelAssociatesMaterial"):
            continue
        mat = rel.RelatingMaterial
        if mat.is_a("IfcMaterialLayerSetUsage"):
            mat = mat.ForLayerSet
        if mat.is_a("IfcMaterialLayerSet"):
            model = _model_of(element)
            scale = length_scale_to_mm(model) if model is not None else 1.0
            return [
                (
                    layer.Material.Name if layer.Material else "?",
                    round(float(layer.LayerThickness) * scale, 2),
                )
                for layer in mat.MaterialLayers
            ]
    return None


@dataclass
class LayerQuantity:
    material: str
    thickness_mm: float
    volume_m3: float


@dataclass
class ElementQuantity:
    guid: str
    ifc_type: str
    name: str
    tag: str
    net_volume_m3: float
    gross_volume_m3: float
    thickness_mm: float | None = None
    thickness_inferred: bool = False
    layers: list[LayerQuantity] = field(default_factory=list)

    @property
    def net_area_m2(self) -> float | None:
        if not self.thickness_mm:
            return None
        return self.net_volume_m3 / (self.thickness_mm / 1000.0)

    @property
    def gross_area_m2(self) -> float | None:
        if not self.thickness_mm:
            return None
        return self.gross_volume_m3 / (self.thickness_mm / 1000.0)


@dataclass
class OpeningQuantity:
    guid: str
    ifc_type: str
    name: str
    width_mm: float | None
    height_mm: float | None

    @property
    def area_m2(self) -> float | None:
        if not self.width_mm or not self.height_mm:
            return None
        return (self.width_mm / 1000.0) * (self.height_mm / 1000.0)


@dataclass
class ModelQuantities:
    source: str
    elements: list[ElementQuantity] = field(default_factory=list)
    openings: list[OpeningQuantity] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)   # no geometry at all
    no_build_up: list[str] = field(default_factory=list)  # volume only, no area

    # -- aggregates ---------------------------------------------------------

    def by_type(self, ifc_type: str) -> list[ElementQuantity]:
        return [e for e in self.elements if e.ifc_type == ifc_type]

    def area_by_tag(self, ifc_type: str | None = None, gross: bool = True) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.elements:
            if ifc_type and e.ifc_type != ifc_type:
                continue
            a = e.gross_area_m2 if gross else e.net_area_m2
            if a is not None:
                out[e.tag] = out.get(e.tag, 0.0) + a
        return out

    def volume_by_type(self, ifc_type: str, gross: bool = False) -> float:
        return sum(
            (e.gross_volume_m3 if gross else e.net_volume_m3)
            for e in self.elements
            if e.ifc_type == ifc_type
        )

    def volume_by_material(self) -> dict[str, float]:
        """Per-material volume across the model -- the Stage 3 input."""
        out: dict[str, float] = {}
        for e in self.elements:
            for layer in e.layers:
                out[layer.material] = out.get(layer.material, 0.0) + layer.volume_m3
        return out

    def exterior_wall_area_m2(self, gross: bool = True) -> float:
        return sum(
            a
            for tag, a in self.area_by_tag("IfcWall", gross).items()
            if wall_role(tag) == "exterior"
        )

    def foundation_wall_area_m2(self, gross: bool = True) -> float:
        return sum(
            a
            for tag, a in self.area_by_tag("IfcWall", gross).items()
            if wall_role(tag) == "foundation"
        )

    def interior_wall_area_m2(self, gross: bool = True) -> float:
        return sum(
            a
            for tag, a in self.area_by_tag("IfcWall", gross).items()
            if wall_role(tag) == "interior"
        )

    def area_by_role(self, gross: bool = True) -> dict[str, float]:
        out: dict[str, float] = {}
        for tag, a in self.area_by_tag("IfcWall", gross).items():
            out[wall_role(tag)] = out.get(wall_role(tag), 0.0) + a
        return out

    def opening_area_m2(self) -> float:
        return sum(o.area_m2 or 0.0 for o in self.openings)

    @property
    def n_inferred(self) -> int:
        return sum(1 for e in self.elements if e.thickness_inferred)


def _opening_size(element) -> tuple[float | None, float | None]:
    """Window/door size, preferring the declared attributes over geometry."""
    w = getattr(element, "OverallWidth", None)
    h = getattr(element, "OverallHeight", None)
    if w and h:
        return float(w), float(h)
    return (float(w) if w else None), (float(h) if h else None)


@lru_cache(maxsize=8)
def model_quantities(ifc_path: str | Path) -> ModelQuantities:
    """Quantify one IFC model. Cached: shape building costs a few seconds."""
    import ifcopenshell
    import ifcopenshell.geom as geom

    model = ifcopenshell.open(str(ifc_path))
    net_cfg = geom.settings()
    net_cfg.set("use-world-coords", True)
    gross_cfg = geom.settings()
    gross_cfg.set("use-world-coords", True)
    gross_cfg.set("disable-opening-subtractions", True)

    result = ModelQuantities(source=str(ifc_path))

    all_types = WALL_TYPES + SLAB_TYPES + FOOTING_TYPES + ROOF_TYPES
    elements = [
        el
        for t in all_types
        for el in model.by_type(t)
        if not is_site_element(getattr(el, "Name", None))
    ]

    # Learn tag -> build-up from the elements that declare one, so elements
    # with no material association can still be quantified.
    tag_layers: dict[str, list[tuple[str, float]]] = {}
    for el in elements:
        layers = material_layers(el)
        if layers:
            tag_layers.setdefault(assembly_tag(el.Name), layers)

    for el in elements:
        tag = assembly_tag(el.Name)
        layers = material_layers(el)
        inferred = False
        if layers is None:
            layers = tag_layers.get(tag)
            inferred = layers is not None

        try:
            net_v = _mesh_volume(geom.create_shape(net_cfg, el))
            gross_v = _mesh_volume(geom.create_shape(gross_cfg, el))
        except Exception:
            result.unassigned.append(f"{el.is_a()} {el.Name or el.GlobalId} (no geometry)")
            continue

        # An element with no build-up still yields a VOLUME, and volume is what
        # concrete needs -- footings and roofs in these models carry no layer
        # set, and dropping them would discard the single largest carbon
        # contributor (concrete, ~35%). Only area is unavailable without a
        # thickness, so it stays None rather than being guessed.
        thickness = sum(t for _, t in layers) if layers else 0.0
        eq = ElementQuantity(
            guid=el.GlobalId,
            ifc_type="IfcWall" if el.is_a("IfcWall") else el.is_a(),
            name=el.Name or "",
            tag=tag,
            net_volume_m3=net_v,
            gross_volume_m3=gross_v,
            thickness_mm=thickness or None,
            thickness_inferred=inferred,
        )
        # Per-layer volume follows from the area, which is why area is derived
        # as volume/thickness rather than from face geometry.
        area = eq.gross_area_m2
        if area is not None and layers:
            eq.layers = [
                LayerQuantity(material=name, thickness_mm=t, volume_m3=area * (t / 1000.0))
                for name, t in layers
            ]
        elif not layers:
            result.no_build_up.append(f"{el.is_a()} {tag}")
        result.elements.append(eq)

    for t in OPENING_TYPES:
        for el in model.by_type(t):
            if is_site_element(getattr(el, "Name", None)):
                continue
            w, h = _opening_size(el)
            result.openings.append(
                OpeningQuantity(
                    guid=el.GlobalId, ifc_type=el.is_a(), name=el.Name or "", width_mm=w, height_mm=h
                )
            )

    return result
