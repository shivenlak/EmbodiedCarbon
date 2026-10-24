"""Parsing of assembly schedules and opening schedules.

Extracts:
  - Assemblies Schedule (A002/A003): W1-W3 (exterior wall), N1 (foundation),
    P1-P5 (interior partition), R1-R3 (roof), F1-F4 (floor).
    Each assembly carries its layer build-up (material description, thickness mm,
    R-value/RSI, performance notes).
  - Openings Schedule (A004): Door Schedule (DA*, DB*, DD*) and Window Schedule
    (WA*, WB*, WC*), with metric and imperial sizes, types, and comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

from ecarbon.geometry.scale import parse_dimension, parse_imperial, parse_metric


@dataclass
class AssemblyLayer:
    """One material layer in a wall, roof, or floor assembly."""

    material_name: str
    thickness_mm: float
    description: str = ""
    is_framing: bool = False
    is_cavity_fill: bool = False
    is_finish: bool = False
    is_membrane: bool = False


@dataclass
class AssemblySpec:
    """An assembly parsed from A002/A003 ASSEMBLIES SCHEDULE."""

    tag: str  # W1, W2, N1, R1, F1, P1, etc.
    category: str  # exterior_wall, foundation_wall, roof, floor, partition
    title: str
    layers: list[AssemblyLayer] = field(default_factory=list)
    r_value: float | None = None
    rsi: float | None = None
    stc: int | None = None
    frr: str | None = None
    page: int = 0
    sheet_no: str = ""
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class ScheduledOpening:
    """One window or door entry from A004 OPENINGS SCHEDULE."""

    tag: str  # DA01, WA01, etc.
    category: Literal["window", "door"]
    opening_type: str  # e.g. "WINDOW TYPE A", "DOOR TYPE A"
    width_mm: float
    height_mm: float
    width_ft_in: str = ""
    height_ft_in: str = ""
    is_exterior: bool = False
    fire_rating: str | None = None
    comments: str = ""
    page: int = 0
    sheet_no: str = ""
    bbox: tuple[float, float, float, float] | None = None

    @property
    def area_m2(self) -> float:
        return (self.width_mm / 1000.0) * (self.height_mm / 1000.0)


# Regular expressions for schedule parsing
_ASSEMBLY_TAG_RE = re.compile(r"^([WNPRF][0-9]{1,2}[a-z]?)$", re.I)
_THICKNESS_MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.I)
_THICKNESS_INCH_RE = re.compile(r"(\d+(?:\s+\d+/\d+|\.\d+)?)\s*[\"']", re.I)
_R_VAL_RE = re.compile(r"R[\s\-\:]*(\d+(?:\.\d+)?)", re.I)
_RSI_VAL_RE = re.compile(r"RSI[\s\-\:]*(\d+(?:\.\d+)?)", re.I)

# Mapping from tag prefix to category
TAG_CATEGORY_MAP = {
    "W": "exterior_wall",
    "EW": "exterior_wall",
    "N": "foundation_wall",
    "P": "partition",
    "R": "roof",
    "F": "floor",
}


def _classify_material_desc(desc: str) -> tuple[str, bool, bool, bool, bool]:
    """Classify a layer description into a standardized material name and flags.

    Returns: (cmhc_mat_name, is_framing, is_cavity_fill, is_finish, is_membrane)
    """
    up = desc.upper()
    is_framing = "STUD" in up or "FRAMING" in up or "JOIST" in up or "FURRING" in up
    is_cavity_fill = "BATT" in up or "CAVITY IN-FILL" in up or "FIBER" in up
    is_finish = "GYPSUM" in up or "FLOOR FINISH" in up or "CLADDING" in up or "PARGING" in up
    is_membrane = "BARRIER" in up or "MEMBRANE" in up or "DAMP PROOFING" in up

    if "CONCRETE" in up or "GRADE BEAM" in up:
        return "CMHC_Concrete Ready Mix 25MPa", False, False, False, False
    if "WOOD STUD" in up or "WOOD ROOF FRAMING" in up or "WOOD FRAMED" in up:
        return "CMHC_Wood Framing", True, False, False, False
    if "METAL STUD" in up or "METAL Z-GIRT" in up:
        return "CMHC_Light Gauge Steel Studs", True, False, False, False
    if "PLYWOOD" in up or "SHEATHING" in up or "SUBFLOOR" in up or "STRAPPING" in up:
        return "CMHC_Plywood", False, False, False, False
    if "GYPSUM" in up:
        return "CMHC_Gypsum Board", False, False, True, False
    if "RIGID INSULATION" in up:
        return "CMHC_Rigid Insulation", False, False, False, False
    if "BATT" in up or "IN-FILL INSULATION" in up:
        return "CMHC_Batt Insulation", False, True, False, False
    if "CLADDING" in up:
        return "CMHC_Vinyl Siding", False, False, True, False
    if "ROOFING" in up or "ROOF MEMBRANE" in up:
        return "CMHC_Roofing", False, False, False, True
    if is_membrane:
        return "CMHC_Building Paper/Membrane", False, False, False, True

    return "CMHC_Wood Framing" if is_framing else desc.strip(), is_framing, is_cavity_fill, is_finish, is_membrane


def parse_assembly_schedule_page(page: pymupdf.Page, page_num: int, sheet_no: str = "A003") -> dict[str, AssemblySpec]:
    """Parse assembly definitions from an assembly schedule sheet."""
    text_blocks = page.get_text("blocks")
    assemblies: dict[str, AssemblySpec] = {}

    current_cat = "exterior_wall"
    
    # Sort blocks top-to-bottom, left-to-right
    blocks_sorted = sorted(text_blocks, key=lambda b: (round(b[0] / 300), b[1]))

    for b in blocks_sorted:
        text = b[4].strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            continue

        first_line = lines[0].upper()
        if "EXTERIOR WALL ASSEMBLIES" in first_line:
            current_cat = "exterior_wall"
            continue
        elif "FOUNDATION WALL" in first_line:
            current_cat = "foundation_wall"
            continue
        elif "INTERIOR PARTITION" in first_line:
            current_cat = "partition"
            continue
        elif "ROOF ASSEMBLIES" in first_line:
            current_cat = "roof"
            continue
        elif "FLOOR ASSEMBLIES" in first_line:
            current_cat = "floor"
            continue

        # Look for assembly tag
        for i, line in enumerate(lines):
            m = _ASSEMBLY_TAG_RE.match(line)
            if m:
                tag = m.group(1).upper()
                prefix = tag[0] if not tag.startswith("EW") else "EW"
                cat = TAG_CATEGORY_MAP.get(prefix, current_cat)

                title = ""
                # Title often appears nearby
                if i + 1 < len(lines):
                    title = lines[i + 1]

                spec = AssemblySpec(
                    tag=tag,
                    category=cat,
                    title=title,
                    page=page_num,
                    sheet_no=sheet_no,
                    bbox=(b[0], b[1], b[2], b[3]),
                )
                assemblies[tag] = spec

    # Second pass: scan full text for layer thickness and descriptions under each tag
    full_text = page.get_text()
    for tag, spec in assemblies.items():
        # Match pattern like: tag followed by description lines up to next tag or section
        pattern = rf"\b{re.escape(tag)}\b(.*?)(?=\b[WNPRF][0-9]{{1,2}}\b|DISCLAIMER|\Z)"
        match = re.search(pattern, full_text, re.DOTALL)
        if match:
            chunk = match.group(1)
            # Find R/RSI values
            r_m = _R_VAL_RE.search(chunk)
            if r_m:
                try:
                    spec.r_value = float(r_m.group(1))
                except ValueError:
                    pass
            rsi_m = _RSI_VAL_RE.search(chunk)
            if rsi_m:
                try:
                    spec.rsi = float(rsi_m.group(1))
                except ValueError:
                    pass

            # Extract layer descriptions and thicknesses
            # Lines like: 140mm (5 1/2") \n WOOD STUD FRAMING
            raw_lines = [l.strip() for l in chunk.split("\n") if l.strip()]
            cur_th = 0.0
            for l in raw_lines:
                th_m = _THICKNESS_MM_RE.search(l)
                if th_m:
                    try:
                        cur_th = float(th_m.group(1))
                    except ValueError:
                        cur_th = 0.0
                    continue

                if cur_th > 0 and len(l) > 3 and not any(k in l.upper() for k in ("TYPE", "DIAGRAM", "PERFORMANCE", "R-VALUE", "STC", "FRR", "EXTERIOR", "INTERIOR")):
                    mat_key, is_frame, is_cav, is_fin, is_mem = _classify_material_desc(l)
                    spec.layers.append(
                        AssemblyLayer(
                            material_name=mat_key,
                            thickness_mm=cur_th,
                            description=l,
                            is_framing=is_frame,
                            is_cavity_fill=is_cav,
                            is_finish=is_fin,
                            is_membrane=is_mem,
                        )
                    )
                    cur_th = 0.0

    return assemblies


def parse_openings_schedule_page(page: pymupdf.Page, page_num: int, sheet_no: str = "A004") -> dict[str, ScheduledOpening]:
    """Parse window and door tags and dimensions from an openings schedule sheet."""
    text = page.get_text()
    openings: dict[str, ScheduledOpening] = {}

    # Find Door Schedule and Window Schedule blocks
    # Table layout:
    # TAG \n TYPE \n METRIC SIZE (mm) \n WIDTH \n HEIGHT ...
    # DA01 \n DOOR TYPE A \n 965 \n 2349 \n 3'-2" \n 7'-8 1/2" ...
    door_tag_re = re.compile(
        r"\b(D[A-Z0-9]{2,3})\s+(DOOR\s+TYPE\s+[A-Z0-9]+)\s+(\d{3,4})\s+(\d{3,4})(?:\s+([0-9'\-\"\s/]+)\s+([0-9'\-\"\s/]+))?",
        re.I,
    )
    for m in door_tag_re.finditer(text):
        tag = m.group(1).upper()
        op_type = m.group(2).upper()
        w_mm = float(m.group(3))
        h_mm = float(m.group(4))
        w_imp = m.group(5).strip() if m.group(5) else ""
        h_imp = m.group(6).strip() if m.group(6) else ""
        is_ext = tag.startswith("DA") or "EXTERIOR" in op_type

        openings[tag] = ScheduledOpening(
            tag=tag,
            category="door",
            opening_type=op_type,
            width_mm=w_mm,
            height_mm=h_mm,
            width_ft_in=w_imp,
            height_ft_in=h_imp,
            is_exterior=is_ext,
            page=page_num,
            sheet_no=sheet_no,
        )

    # Windows: WA01 \n WINDOW TYPE A \n 600 \n 600 ...
    win_tag_re = re.compile(
        r"\b(W[A-Z0-9]{2,3})\s+(WINDOW\s+TYPE\s+[A-Z0-9]+)\s+(\d{3,4})\s+(\d{3,4})(?:\s+([0-9'\-\"\s/]+)\s+([0-9'\-\"\s/]+))?",
        re.I,
    )
    for m in win_tag_re.finditer(text):
        tag = m.group(1).upper()
        op_type = m.group(2).upper()
        w_mm = float(m.group(3))
        h_mm = float(m.group(4))
        w_imp = m.group(5).strip() if m.group(5) else ""
        h_imp = m.group(6).strip() if m.group(6) else ""

        openings[tag] = ScheduledOpening(
            tag=tag,
            category="window",
            opening_type=op_type,
            width_mm=w_mm,
            height_mm=h_mm,
            width_ft_in=w_imp,
            height_ft_in=h_imp,
            is_exterior=True,  # Windows on exterior envelope
            page=page_num,
            sheet_no=sheet_no,
        )

    # If regex missed any due to newline separation in table columns:
    # Look for tabular rows
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        # Match door tag like DA01, DB01, DD01
        if re.match(r"^D[A-Z0-9]{2,3}$", line) and line not in openings:
            tag = line.upper()
            # Look ahead for sizes
            nums = []
            for j in range(i + 1, min(i + 8, len(lines))):
                if re.match(r"^\d{3,4}$", lines[j]):
                    nums.append(float(lines[j]))
                    if len(nums) == 2:
                        break
            if len(nums) == 2:
                openings[tag] = ScheduledOpening(
                    tag=tag,
                    category="door",
                    opening_type="DOOR",
                    width_mm=nums[0],
                    height_mm=nums[1],
                    is_exterior=tag.startswith("DA"),
                    page=page_num,
                    sheet_no=sheet_no,
                )

        # Match window tag like WA01, WB02
        elif re.match(r"^W[A-C][0-9]{2}$", line) and line not in openings:
            tag = line.upper()
            nums = []
            for j in range(i + 1, min(i + 8, len(lines))):
                if re.match(r"^\d{3,4}$", lines[j]):
                    nums.append(float(lines[j]))
                    if len(nums) == 2:
                        break
            if len(nums) == 2:
                openings[tag] = ScheduledOpening(
                    tag=tag,
                    category="window",
                    opening_type="WINDOW",
                    width_mm=nums[0],
                    height_mm=nums[1],
                    is_exterior=True,
                    page=page_num,
                    sheet_no=sheet_no,
                )

    return openings
