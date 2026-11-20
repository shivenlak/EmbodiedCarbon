"""The vision fallback, on recorded answers: CI never calls a provider."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from ecarbon.models import Confidence
from ecarbon.vision import DPI, Task, provider_from_env, read_page
from ecarbon.vision import cache as vcache
from ecarbon.vision.validate import RASTER_NOTE, box_to_points, validate

FIXTURES = Path(__file__).parent / "fixtures" / "vision"


def answer(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def plan_page(rotation: int = 0) -> pymupdf.Page:
    """A sheet printing an overall width and depth where the fixtures say."""
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((100, 100), "9100", fontsize=12)
    page.insert_text((400, 300), "7'-6\"", fontsize=12)
    page.set_rotation(rotation)
    return page


class TestQuoteAndLocate:
    def test_a_quote_printed_where_the_model_says_is_kept(self):
        got = {
            r.field: r
            for r in validate(plan_page(), "A101", Task.FOOTPRINT, answer("footprint_found"), DPI)
        }
        assert got["width"].value == 9100
        assert got["width"].note == "vision: A101: '9100'"
        assert got["width"].confidence is Confidence.INFERRED
        # The kept box is where the text is printed, in PDF points.
        assert got["width"].bbox[0] == pytest.approx(100, abs=1)

    def test_the_number_comes_from_the_quote_not_the_model(self):
        got = {
            r.field: r
            for r in validate(plan_page(), "A101", Task.FOOTPRINT, answer("footprint_found"), DPI)
        }
        assert got["depth"].value == pytest.approx(7.5 * 304.8, abs=1)

    def test_a_hallucinated_quote_is_dropped(self):
        got = {
            r.field
            for r in validate(
                plan_page(), "A101", Task.FOOTPRINT, answer("footprint_hallucinated"), DPI
            )
        }
        # 12500 is printed nowhere; 7'-6" is printed, but not where it was claimed.
        assert got == set()

    def test_not_on_this_sheet_reads_nothing(self):
        assert validate(plan_page(), "A101", Task.FOOTPRINT, answer("not_found"), DPI) == []

    def test_a_rotated_sheet_maps_the_box_back_to_page_points(self):
        page = plan_page(rotation=90)
        # Where "9100" lands on the rendered, rotated image.
        r = pymupdf.Rect(100, 87, 126, 104) * page.rotation_matrix * (DPI / 72.0)
        r.normalize()
        back = box_to_points(page, list(r), DPI)
        assert back.x0 == pytest.approx(100, abs=1) and back.y0 == pytest.approx(87, abs=1)
        ans = {"found": True, "width": {"quote": "9100", "box": list(r)}}
        assert [x.value for x in validate(page, None, Task.FOOTPRINT, ans, DPI)] == [9100]

    def test_a_raster_page_is_kept_but_says_it_cannot_be_checked(self):
        blank = pymupdf.open().new_page(width=800, height=600)
        got = validate(blank, "A101", Task.FOOTPRINT, answer("footprint_found"), DPI)
        assert {r.field for r in got} == {"width", "depth"}
        assert all(r.confidence is Confidence.INFERRED and RASTER_NOTE in r.note for r in got)


class Recorded:
    name, model = "recorded", "fixture"

    def __init__(self, fixture: str):
        self.fixture, self.calls = fixture, 0

    def read(self, png, task):
        self.calls += 1
        return answer(self.fixture)


def test_a_page_is_paid_for_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ECARBON_VISION_CACHE", str(tmp_path))
    provider = Recorded("footprint_found")
    for _ in range(2):
        assert len(read_page(provider, plan_page(), "A101", Task.FOOTPRINT)) == 2
    assert provider.calls == 1
    assert vcache.cache_dir() == tmp_path


def test_vision_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("ECARBON_VISION", raising=False)
    assert provider_from_env() is None


def test_a_line_on_a_vision_footprint_says_so():
    """Contract C3: INFERRED, a 'vision: ' note, an assumption naming the model, a bbox."""
    from ecarbon.geometry.footprint import Footprint
    from ecarbon.models import Basis, BasisSource, ElementClass, Provenance, TakeoffLine, Unit
    from ecarbon.takeoff.builder import TakeoffInputs, label_vision

    readings = validate(plan_page(), "A101", Task.FOOTPRINT, answer("footprint_found"), DPI)
    inputs = TakeoffInputs(
        footprint=Footprint(9.1, 2.286, basis=[r.note for r in readings]),
        footprint_sheet="A101",
        footprint_page=3,
        vision=readings,
        vision_by="recorded (fixture)",
    )
    line = TakeoffLine(
        id="ln-slab-on-grade",
        element_class=ElementClass.SLAB_ON_GRADE,
        quantity=2.1,
        unit=Unit.M3,
        confidence=Confidence.MEASURED,
        basis=Basis(sources=[BasisSource.VECTOR_PATH], note="measured from linework"),
        provenance=Provenance(page=3, sheet_no="A101"),
    )
    label_vision([line], inputs)
    assert line.confidence is Confidence.INFERRED
    assert line.basis.note.startswith("vision: A101: '9100'")
    assert "linework did not confirm" in line.basis.note
    assert BasisSource.VECTOR_PATH not in line.basis.sources
    assert any("recorded (fixture)" in a for a in line.assumptions)
    assert line.provenance.bbox == readings[0].bbox
