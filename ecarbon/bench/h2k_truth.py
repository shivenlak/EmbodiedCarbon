"""HOT2000 XML ground truth parser.

HOT2000 files (.h2k) are plain XML (HOT2000 v11.13) containing energy-compliance
geometry submitted for Canadian residential buildings.

They provide an independent ground truth for:
  - Exterior wall gross area (above grade)
  - Ceiling / roof envelope area
  - Slab perimeter (exposed)
  - Window counts and total area
  - Door counts and total area
  - Heated / conditioned floor area

See RESEARCH.md §6 and docs/PLAN.md Step 9.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class H2KSurface:
    tag: str
    name: str
    area_m2: float
    length_m: float | None = None
    height_m: float | None = None
    perimeter_m: float | None = None


@dataclass(frozen=True)
class H2KWindow:
    label: str
    width_m: float
    height_m: float
    area_m2: float
    facing_direction: str | None = None


@dataclass(frozen=True)
class H2KDoor:
    label: str
    width_m: float
    height_m: float
    area_m2: float


@dataclass(frozen=True)
class H2KTruth:
    file_path: Path
    dwelling_name: str
    city: str
    province: str
    weather_location: str | None

    # Areas in square metres
    exterior_wall_area_m2: float
    ceiling_area_m2: float
    slab_exposed_perimeter_m: float
    heated_floor_area_m2: float | None

    # Openings
    window_count: int
    window_total_area_m2: float
    door_count: int
    door_total_area_m2: float

    # Detailed lists
    walls: list[H2KSurface] = field(default_factory=list)
    ceilings: list[H2KSurface] = field(default_factory=list)
    windows: list[H2KWindow] = field(default_factory=list)
    doors: list[H2KDoor] = field(default_factory=list)


def parse_h2k(file_path: str | Path) -> H2KTruth:
    """Parse a HOT2000 .h2k file into structured ground truth."""
    path = Path(file_path)
    tree = ET.parse(path)
    root = tree.getroot()

    # Client / Project identification
    dwelling_name = ""
    street_el = root.find(".//StreetAddress/Street")
    if street_el is not None and street_el.text:
        dwelling_name = street_el.text.strip()

    city = ""
    city_el = root.find(".//StreetAddress/City")
    if city_el is not None and city_el.text:
        city = city_el.text.strip()

    province = ""
    prov_el = root.find(".//StreetAddress/Province")
    if prov_el is not None and prov_el.text:
        province = prov_el.text.strip()

    weather_loc = None
    w_el = root.find(".//Weather/Location/English")
    if w_el is not None and w_el.text:
        weather_loc = w_el.text.strip()

    # Heated Floor Area
    heated_floor_area = None
    hfa_el = root.find(".//HeatedFloorArea")
    if hfa_el is not None and hfa_el.attrib.get("area"):
        try:
            heated_floor_area = float(hfa_el.attrib["area"])
        except ValueError:
            pass

    # Above-grade exterior walls
    # HOT2000 stores above-grade walls in Components/Walls/Wall or under MainWalls/Wall
    # Wall.Measurements has either height + perimeter, or length + height, or area
    walls: list[H2KSurface] = []
    total_wall_area = 0.0
    walls_seen: set[ET.Element] = set()

    # Search for all above-grade walls
    for wall in root.findall(".//Components/Wall"):
        m = wall.find("Measurements")
        if m is None:
            continue

        type_el = wall.find("Construction/Type")
        wall_name = type_el.text.strip() if type_el is not None and type_el.text else "Wall"

        area = None
        height = None
        perimeter = None
        length = None

        if "area" in m.attrib:
            try:
                area = float(m.attrib["area"])
            except ValueError:
                pass
        if "height" in m.attrib:
            try:
                height = float(m.attrib["height"])
            except ValueError:
                pass
        if "perimeter" in m.attrib:
            try:
                perimeter = float(m.attrib["perimeter"])
            except ValueError:
                pass
        if "length" in m.attrib:
            try:
                length = float(m.attrib["length"])
            except ValueError:
                pass

        if area is None and height is not None:
            span = perimeter if perimeter is not None else length
            if span is not None:
                area = height * span

        if area is not None and area > 0:
            surface = H2KSurface(
                tag="wall",
                name=wall_name,
                area_m2=round(area, 4),
                height_m=height,
                perimeter_m=perimeter,
                length_m=length,
            )
            walls.append(surface)
            total_wall_area += area

    # Ceilings / Roof
    ceilings: list[H2KSurface] = []
    total_ceiling_area = 0.0

    for c in root.findall(".//Components/Ceilings/Ceiling") + root.findall(".//Ceiling"):
        m = c.find("Measurements")
        if m is None or "area" not in m.attrib:
            continue
        try:
            c_area = float(m.attrib["area"])
        except ValueError:
            continue

        type_el = c.find("Construction/CeilingType")
        c_name = type_el.text.strip() if type_el is not None and type_el.text else "Ceiling"

        length = float(m.attrib["length"]) if "length" in m.attrib else None

        surface = H2KSurface(
            tag="ceiling",
            name=c_name,
            area_m2=round(c_area, 4),
            length_m=length,
        )
        ceilings.append(surface)
        total_ceiling_area += c_area

    # Slab exposed perimeter
    slab_perimeter = 0.0
    for slab in root.findall(".//Slab"):
        if "exposedSurfacePerimeter" in slab.attrib:
            try:
                p_val = float(slab.attrib["exposedSurfacePerimeter"])
                slab_perimeter = max(slab_perimeter, p_val)
            except ValueError:
                pass

    # Windows
    # HOT2000 Measurements in mm: height, width
    windows: list[H2KWindow] = []
    total_win_area = 0.0

    for win in root.findall(".//Window"):
        m = win.find("Measurements")
        if m is None:
            continue
        try:
            w_mm = float(m.attrib.get("width", 0))
            h_mm = float(m.attrib.get("height", 0))
        except ValueError:
            continue

        lbl_el = win.find("Label")
        label = lbl_el.text.strip() if lbl_el is not None and lbl_el.text else "Window"

        dir_el = win.find("FacingDirection")
        facing = dir_el.find("English").text.strip() if dir_el is not None and dir_el.find("English") is not None else None

        w_m = w_mm / 1000.0 if w_mm > 50 else w_mm  # handle mm vs m
        h_m = h_mm / 1000.0 if h_mm > 50 else h_mm
        area = w_m * h_m

        if area > 0:
            windows.append(
                H2KWindow(
                    label=label,
                    width_m=round(w_m, 4),
                    height_m=round(h_m, 4),
                    area_m2=round(area, 4),
                    facing_direction=facing,
                )
            )
            total_win_area += area

    # Doors
    # HOT2000 Measurements in metres: height, width
    doors: list[H2KDoor] = []
    total_door_area = 0.0

    for d in root.findall(".//Door"):
        m = d.find("Measurements")
        if m is None:
            continue
        try:
            w_raw = float(m.attrib.get("width", 0))
            h_raw = float(m.attrib.get("height", 0))
        except ValueError:
            continue

        lbl_el = d.find("Label")
        label = lbl_el.text.strip() if lbl_el is not None and lbl_el.text else "Door"

        w_m = w_raw / 1000.0 if w_raw > 50 else w_raw
        h_m = h_raw / 1000.0 if h_raw > 50 else h_raw
        area = w_m * h_m

        if area > 0:
            doors.append(
                H2KDoor(
                    label=label,
                    width_m=round(w_m, 4),
                    height_m=round(h_m, 4),
                    area_m2=round(area, 4),
                )
            )
            total_door_area += area

    return H2KTruth(
        file_path=path,
        dwelling_name=dwelling_name,
        city=city,
        province=province,
        weather_location=weather_loc,
        exterior_wall_area_m2=round(total_wall_area, 2),
        ceiling_area_m2=round(total_ceiling_area, 2),
        slab_exposed_perimeter_m=round(slab_perimeter, 2),
        heated_floor_area_m2=round(heated_floor_area, 2) if heated_floor_area else None,
        window_count=len(windows),
        window_total_area_m2=round(total_win_area, 2),
        door_count=len(doors),
        door_total_area_m2=round(total_door_area, 2),
        walls=walls,
        ceilings=ceilings,
        windows=windows,
        doors=doors,
    )
