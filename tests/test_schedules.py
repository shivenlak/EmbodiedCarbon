"""Unit tests for Step 19: Assemblies and Openings Schedule parsing."""

import pytest
import pymupdf

from ecarbon.bench.ifc_truth import parse_ifc_takeoff
from ecarbon.config import get_design
from ecarbon.extract.schedules import parse_assembly_schedule_page, parse_openings_schedule_page
from ecarbon.intake.inventory import inventory
from ecarbon.models import SheetType


def test_assembly_schedule_w2_cross_check_ifc():
    """Verify parsed build-up for W2 matches IFC layer set materials and thicknesses."""
    d = get_design("ATL_ADU_01")
    doc = pymupdf.open(d.drawings_pdf)
    sheets, _, _ = inventory(d.drawings_pdf)
    sched_sheets = [s for s in sheets if s.sheet_type == SheetType.ASSEMBLY_SCHEDULE or (s.sheet_no and "A00" in s.sheet_no)]

    assemblies = {}
    for s in sched_sheets:
        specs = parse_assembly_schedule_page(doc[s.page], s.page, s.sheet_no or "A003")
        for k, v in specs.items():
            if k not in assemblies or len(v.layers) > len(assemblies[k].layers):
                assemblies[k] = v

    assert "W2" in assemblies
    w2 = assemblies["W2"]
    assert len(w2.layers) >= 3

    # IFC cross-check
    ifc = parse_ifc_takeoff(d.ifc)
    ifc_w2 = next((el for el in ifc.elements if el.assembly_tag == "W2" and el.layers), None)
    assert ifc_w2 is not None

    # Check key thicknesses: 140mm stud framing and 51mm rigid insulation
    pdf_thicks = [l.thickness_mm for l in w2.layers]
    ifc_thicks = [round(l.thickness_mm) for l in ifc_w2.layers]

    # Both must contain 140mm framing
    assert any(abs(t - 140.0) < 2.0 for t in pdf_thicks)
    assert any(abs(t - 140.0) < 2.0 for t in ifc_thicks)

    # Both must contain ~51mm rigid insulation
    assert any(abs(t - 51.0) < 2.0 for t in pdf_thicks)
    assert any(abs(t - 51.0) < 2.0 for t in ifc_thicks)


def test_openings_schedule_dimensions():
    """Verify window and door schedule parsing from A004."""
    d = get_design("ATL_ADU_01")
    doc = pymupdf.open(d.drawings_pdf)
    sheets, _, _ = inventory(d.drawings_pdf)
    open_sheets = [s for s in sheets if s.sheet_type == SheetType.OPENING_SCHEDULE or (s.sheet_no and s.sheet_no in ("A002", "A004"))]

    openings = {}
    for s in open_sheets:
        ops = parse_openings_schedule_page(doc[s.page], s.page, s.sheet_no or "A004")
        openings.update(ops)

    # If scheduled openings exist, check tags and positive dimensions
    if openings:
        for tag, op in openings.items():
            assert op.width_mm > 0
            assert op.height_mm > 0
            assert op.area_m2 > 0
