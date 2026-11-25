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


def section_page() -> pymupdf.Page:
    """A section printing two datums where levels_found.json says."""
    page = pymupdf.open().new_page(width=800, height=600)
    for pt, text in [
        ((500, 200), "SECOND FLOOR"),
        ((500, 212), "3.000 m"),
        ((500, 400), "MAIN FLOOR"),
        ((500, 412), "0.000 m"),
        ((100, 500), "KITCHEN"),
    ]:
        page.insert_text(pt, text, fontsize=9)
    return page


class TestLevelDatums:
    def test_a_datum_needs_its_label_and_its_elevation(self):
        got = validate(section_page(), "A301", Task.LEVELS, answer("levels_found"), DPI)
        # KITCHEN is not a level label; THIRD FLOOR / 6.000 m are printed nowhere.
        assert [(r.field, r.value) for r in got] == [("SECOND FLOOR", 3.0), ("MAIN FLOOR", 0.0)]
        assert got[0].note == "vision: A301: 'SECOND FLOOR' '3.000 m'"

    def test_datums_become_storey_heights(self):
        from ecarbon.extract.levels import Level, StoreyHeights

        got = validate(section_page(), "A301", Task.LEVELS, answer("levels_found"), DPI)
        h = StoreyHeights(levels=[Level(r.field, r.value) for r in got])
        assert h.storey_heights_m() == [3.0, 3.0]


def test_a_wall_on_vision_heights_keeps_its_own_note_behind_the_quotes():
    from ecarbon.extract.levels import Level, StoreyHeights
    from ecarbon.models import Basis, BasisSource, ElementClass, Provenance, TakeoffLine, Unit
    from ecarbon.takeoff.builder import TakeoffInputs, label_vision

    got = validate(section_page(), "A301", Task.LEVELS, answer("levels_found"), DPI)
    inputs = TakeoffInputs(
        heights=StoreyHeights(levels=[Level(r.field, r.value) for r in got]),
        vision_levels=got,
        vision_levels_page=7,
        vision_by="recorded (fixture)",
    )
    wall = TakeoffLine(
        id="ln-exterior-wall",
        element_class=ElementClass.EXTERIOR_WALL,
        quantity=200.0,
        unit=Unit.M2,
        confidence=Confidence.INFERRED,
        basis=Basis(sources=[BasisSource.VECTOR_PATH], note="perimeter off the linework"),
        provenance=Provenance(page=3, sheet_no="A101"),
    )
    slab = wall.model_copy(update={"id": "ln-slab", "element_class": ElementClass.SLAB_ON_GRADE})
    label_vision([wall, slab], inputs)
    assert wall.basis.note.startswith("vision: A301: 'SECOND FLOOR' '3.000 m'")
    assert wall.basis.note.endswith("perimeter off the linework")
    assert BasisSource.VECTOR_PATH in wall.basis.sources
    assert any("Level datums" in a for a in wall.assumptions)
    # A slab does not rest on storey heights.
    assert slab.basis.note == "perimeter off the linework"


class TestOutlinedText:
    """A sheet whose dimensions are linework, with only a stamp as text (NOR)."""

    def stamped_page(self) -> pymupdf.Page:
        doc = pymupdf.open()
        page = doc.new_page(width=800, height=600)
        page.insert_text((600, 580), "NOT FOR PERMIT", fontsize=8)
        page.insert_text((600, 590), "OR CONSTRUCTION", fontsize=8)
        return page

    def test_a_text_layer_without_a_number_is_checked_as_an_image(self):
        got = {
            r.field: r
            for r in validate(self.stamped_page(), "A100", Task.FOOTPRINT, answer("footprint_found"), DPI)
        }
        assert got["width"].value == 9100
        assert got["width"].confidence is Confidence.INFERRED
        assert RASTER_NOTE in got["width"].note

    def test_one_number_in_the_text_keeps_the_full_check(self):
        page = self.stamped_page()
        page.insert_text((50, 50), "REV 2", fontsize=8)
        got = validate(page, "A100", Task.FOOTPRINT, answer("footprint_hallucinated"), DPI)
        assert got == []


class TestRender:
    def test_a_sheet_too_large_to_send_is_rendered_smaller(self, monkeypatch):
        from ecarbon import vision

        monkeypatch.setattr(vision, "MAX_PNG_BYTES", 20_000)
        page = plan_page()
        for i in range(400):  # enough ink to make the PNG large
            page.draw_line((i * 2, 0), (800 - i * 2, 600))
        png, dpi = vision.render(page)
        assert dpi < DPI
        assert len(png) <= 20_000 or dpi <= 40


class TestVisionSheetTypes:
    def test_an_unclassified_page_is_typed_from_its_vision_read_title(self, monkeypatch):
        import ecarbon.takeoff.builder as b
        from ecarbon.models import SheetInfo, SheetType
        from ecarbon.vision.validate import Reading

        def fake_read(provider, page, sheet_no, task):
            assert task is Task.SHEET
            n = Confidence.INFERRED
            return [
                Reading("sheet_no", "A100", "A100", (0, 0, 1, 1), n, "vision: page 1: 'A100'"),
                Reading("title", "MAIN FLOOR PLAN", "MAIN FLOOR PLAN", (0, 0, 1, 1), n, "vision"),
            ]

        monkeypatch.setattr(b, "read_page", fake_read)
        sheets = [SheetInfo(page=0, sheet_type=SheetType.UNKNOWN)]
        inputs = b.TakeoffInputs()
        got = b._vision_candidates(object(), [None], sheets, inputs, b.PLAN_TYPES)
        assert [(s.page, s.sheet_no, s.sheet_type) for s in got] == [(0, "A100", SheetType.FLOOR_PLAN)]
        assert sheets[0].sheet_type is SheetType.UNKNOWN  # the inventory is untouched


def test_an_el_prefixed_elevation_parses():
    from ecarbon.vision.validate import _value

    assert _value(Task.LEVELS, "elevation", "EL 2.505 m") == 2.505
    assert _value(Task.LEVELS, "elevation", "ELEV. 0.000 m") == 0.0


def test_cache_mode_replays_saved_claude_answers_and_never_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("ECARBON_VISION_CACHE", str(tmp_path))
    monkeypatch.setenv("ECARBON_VISION", "cache")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cached = provider_from_env()
    assert read_page(cached, plan_page(), "A101", Task.FOOTPRINT) == []  # nothing saved yet

    claude = Recorded("footprint_found")
    claude.name, claude.model = cached.name, cached.model  # what a real Claude run saves under
    assert len(read_page(claude, plan_page(), "A101", Task.FOOTPRINT)) == 2
    assert len(read_page(cached, plan_page(), "A101", Task.FOOTPRINT)) == 2


def test_a_seed_store_copies_only_the_answers_used(tmp_path, monkeypatch):
    seed, ship = tmp_path / "seed", tmp_path / "ship"
    monkeypatch.setenv("ECARBON_VISION_CACHE", str(seed))
    claude = Recorded("footprint_found")
    read_page(claude, plan_page(), "A101", Task.FOOTPRINT)
    (seed / "unrelated.json").write_text("{}")

    monkeypatch.setenv("ECARBON_VISION_CACHE", str(ship))
    monkeypatch.setenv("ECARBON_VISION_SEED", str(seed))
    assert len(read_page(claude, plan_page(), "A101", Task.FOOTPRINT)) == 2
    assert claude.calls == 1
    assert sorted(p.name for p in ship.iterdir()) == sorted(
        p.name for p in seed.iterdir() if p.name != "unrelated.json"
    )
