"""User-stated inputs (contract C2): the guided fallback's plumbing.

When the drawings cannot be read, the user states a scale, an outline or the
storey heights. These pin that a stated input is used, is labelled as stated
everywhere it reaches, never claims to be measured, stays in the workspace
that stated it, and that stating nothing changes nothing.
"""

from __future__ import annotations

import pytest

from ecarbon.models import (
    Basis,
    BasisSource,
    Confidence,
    ElementClass,
    Provenance,
    TakeoffLine,
    Unit,
)
from ecarbon.takeoff.overrides import (
    STATED_PREFIX,
    Overrides,
    StatedStoreyHeights,
    footprint_from_polygon,
    label_stated,
    parse_length_mm,
    scale_from_points,
)

try:
    from ecarbon.config import discover

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False
needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestReadingWhatTheUserTyped:
    @pytest.mark.parametrize(
        ("typed", "mm"),
        [
            ("7160", 7160.0),
            (7160, 7160.0),
            ("7.16 m", 7160.0),
            ("7.16", 7160.0),  # under 100 with no unit reads as metres
            ("716 cm", 7160.0),
            ("7160mm", 7160.0),
            ("7,16 m", 7160.0),  # decimal comma
            ("23'-6\"", 23 * 304.8 + 6 * 25.4),
            ("23' 6 1/2\"", 23 * 304.8 + 6.5 * 25.4),
            ("23’-6”", 23 * 304.8 + 6 * 25.4),  # curly quotes from a phone
        ],
    )
    def test_lengths_in_any_unit(self, typed, mm):
        assert parse_length_mm(typed) == pytest.approx(mm, rel=1e-6)

    def test_nonsense_is_refused_not_guessed(self):
        with pytest.raises(ValueError):
            parse_length_mm("about seven metres")

    def test_scale_from_two_points(self):
        # 1/4" = 1'-0": 18 pt on the page is 304.8 mm.
        assert scale_from_points((0, 0), (18 * 10, 0), 3048.0) == pytest.approx(304.8 / 18)

    def test_points_too_close_are_refused(self):
        with pytest.raises(ValueError):
            scale_from_points((0, 0), (1, 1), 3000.0)


class TestStatedGeometry:
    def test_an_l_shaped_outline_is_measured_as_drawn(self):
        # 10 x 8 m with a 4 x 4 m corner removed, at 10 mm per point.
        corners = [(0, 0), (1000, 0), (1000, 400), (600, 400), (600, 800), (0, 800)]
        fp = footprint_from_polygon(corners, mm_per_pt=10.0)
        assert fp.area_m2 == pytest.approx(80 - 16)
        assert fp.perimeter_m == pytest.approx(36.0)
        # The bounding box is still reported, but it is not the area.
        assert (fp.width_m, fp.depth_m) == (10.0, 8.0)
        assert fp.confident

    def test_a_tiny_outline_means_a_wrong_scale(self):
        with pytest.raises(ValueError, match="check the scale"):
            footprint_from_polygon([(0, 0), (10, 0), (10, 10)], mm_per_pt=1.0)

    def test_heights_one_per_storey(self):
        h = StatedStoreyHeights([3.0, 2.8, 2.8], floor_assembly_mm=333.0)
        assert h.storey_heights_m() == [3.0, 2.8, 2.8]
        assert h.n_storeys == 3
        assert h.total_wall_height_m == pytest.approx(8.6)
        assert not h.missing

    def test_an_impossible_storey_is_refused(self):
        with pytest.raises(ValueError):
            StatedStoreyHeights([30.0])


def _line(cls, conf=Confidence.MEASURED, quantity=10.0):
    return TakeoffLine(
        id=f"ln-{cls.value}",
        element_class=cls,
        quantity=quantity,
        unit=Unit.M2,
        confidence=conf,
        basis=Basis(sources=[BasisSource.VECTOR_PATH], note="from the drawings"),
        assumptions=["x"] if conf is Confidence.ASSUMED else [],
        provenance=Provenance(page=0),
    )


class TestLabelling:
    def test_stated_lines_say_so_and_never_claim_measured(self):
        lines = [_line(ElementClass.SLAB_ON_GRADE), _line(ElementClass.WINDOW)]
        label_stated(lines, Overrides(footprint=(0, [(0, 0), (1, 0), (1, 1)])))
        slab, window = lines
        assert slab.basis.note.startswith(STATED_PREFIX)
        assert BasisSource.USER in slab.basis.sources
        assert slab.confidence is Confidence.INFERRED
        # A window count does not rest on the outline.
        assert window.basis.note == "from the drawings"
        assert window.confidence is Confidence.MEASURED

    def test_heights_reach_walls_not_slabs(self):
        lines = [_line(ElementClass.EXTERIOR_WALL), _line(ElementClass.SLAB_ON_GRADE)]
        label_stated(lines, Overrides(storey_heights_m=[3.0]))
        assert lines[0].basis.note.startswith(STATED_PREFIX)
        assert lines[1].basis.note == "from the drawings"

    def test_nothing_stated_changes_nothing(self):
        lines = [_line(ElementClass.SLAB_ON_GRADE)]
        before = lines[0].model_dump()
        label_stated(lines, Overrides())
        label_stated(lines, None)
        assert lines[0].model_dump() == before


@needs_data
class TestBuildingWithStatedInputs:
    @pytest.fixture(scope="class")
    def design(self):
        from ecarbon.config import get_design

        return get_design("AB_Fourplex_01")

    def test_empty_overrides_are_bit_identical(self, design):
        from ecarbon.takeoff.builder import build_takeoff

        a = build_takeoff(design).model_dump(mode="json")
        b = build_takeoff(design, overrides=Overrides()).model_dump(mode="json")
        a.pop("generated_at", None)
        b.pop("generated_at", None)
        assert a == b

    def test_stated_heights_move_the_walls_and_are_labelled(self, design):
        from ecarbon.takeoff.builder import build_takeoff

        base = {ln.id: ln for ln in build_takeoff(design).lines}
        stated = build_takeoff(design, overrides=Overrides(storey_heights_m=[2.8, 2.8]))
        wall = stated.line("ln-exterior-wall")
        assert wall.quantity < base["ln-exterior-wall"].quantity
        assert wall.basis.note.startswith(STATED_PREFIX)
        # The slab does not depend on heights and is untouched.
        assert stated.line("ln-slab-on-grade").quantity == base["ln-slab-on-grade"].quantity


@needs_data
class TestCalibrateEndpoint:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import app

        return TestClient(app)

    @staticmethod
    def _as(workspace: str) -> dict:
        from ecarbon.api.main import _sign

        return {"x-ecarbon-session": _sign(workspace)}

    PID = "AB_Fourplex_01_Technical_Design_Package"

    def test_pages_lists_every_page_with_its_size(self, client):
        pages = client.get(f"/projects/{self.PID}/pages").json()
        assert len(pages) > 20
        assert all(p["width"] > 0 and p["height"] > 0 for p in pages)
        # A section with a usable scale exists, so heights can be clicked.
        assert any(p["sheet_type"] == "section" and p["scale_mm_per_pt"] for p in pages)
        # An estimated scale is only offered at building-section scales.
        for p in pages:
            if p["scale_estimated"]:
                assert 25 <= p["scale_mm_per_pt"] / (25.4 / 72) <= 200
        thumb = client.get(pages[0]["image_url"] + "?dpi=10")
        assert thumb.status_code == 200 and len(thumb.content) < 200_000
        png = client.get(pages[0]["image_url"] + "?dpi=40")
        assert png.status_code == 200 and png.content[:4] == b"\x89PNG"

    def test_stated_heights_apply_in_one_workspace_only(self, client):
        me, them = self._as("calib-me"), self._as("calib-them")
        base = client.get(f"/projects/{self.PID}/carbon", headers=them).json()["total_kg_co2e"]
        r = client.post(
            f"/projects/{self.PID}/calibrate",
            json={"storey_heights": ["9'-2\"", "9'-2\""]},
            headers=me,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stated"]["storey_heights_m"] == pytest.approx([2.794, 2.794])
        assert body["carbon"]["total_kg_co2e"] < base
        wall = next(
            ln for ln in client.get(f"/projects/{self.PID}/takeoff", headers=me).json()["lines"]
            if ln["id"] == "ln-exterior-wall"
        )
        assert wall["basis"]["note"].startswith(STATED_PREFIX)
        assert "user" in wall["basis"]["sources"]
        # Another visitor still sees the drawings alone.
        assert client.get(f"/projects/{self.PID}/carbon", headers=them).json()["total_kg_co2e"] == base
        # And clearing puts this visitor back.
        r = client.post(f"/projects/{self.PID}/calibrate", json={"clear": True}, headers=me)
        assert r.json()["carbon"]["total_kg_co2e"] == pytest.approx(base)

    def test_quantity_corrections_survive_a_calibration(self, client):
        me = self._as("calib-keep")
        client.post(f"/projects/{self.PID}/lines/ln-slab-on-grade", json={"quantity": 25}, headers=me)
        client.post(f"/projects/{self.PID}/calibrate", json={"storey_heights": [3.0, 3.0]}, headers=me)
        slab = next(
            ln for ln in client.get(f"/projects/{self.PID}/takeoff", headers=me).json()["lines"]
            if ln["id"] == "ln-slab-on-grade"
        )
        assert slab["user_override"] == 25

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"storey_heights": ["tall"]},
            {"storey_heights": [40]},
            {"p1": [0, 0], "p2": [100, 0], "length": "7 m"},  # no page
            {"page": 0, "p1": [0, 0], "p2": [1, 0], "length": "7 m"},  # points too close
        ],
    )
    def test_bad_input_is_explained_not_guessed(self, client, body):
        r = client.post(f"/projects/{self.PID}/calibrate", json=body, headers=self._as("calib-bad"))
        assert r.status_code == 422
        assert r.json()["detail"]


@needs_data
class TestTracingTheOutline:
    """Scale, then outline: the two clicks most sets that fail need."""

    PID = "AB_Fourplex_01_Technical_Design_Package"

    def test_a_traced_footprint_reproduces_the_measured_slab(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import _sign, app

        client = TestClient(app)
        me = {"x-ecarbon-session": _sign("calib-outline")}
        # 1:50 on the sheet: 100 pt apart is 100 * 50 * 25.4/72 mm.
        mm = 100 * 50 * 25.4 / 72
        r = client.post(
            f"/projects/{self.PID}/calibrate",
            json={"page": 10, "p1": [0, 0], "p2": [100, 0], "length": f"{mm:.3f}"},
            headers=me,
        )
        assert r.status_code == 200, r.text
        # The measured 7.0 x 22.0 m footprint, traced as four corners.
        k = 1000 / (50 * 25.4 / 72)  # points per metre at 1:50
        corners = [[0, 0], [7.0 * k, 0], [7.0 * k, 22.0 * k], [0, 22.0 * k]]
        r = client.post(f"/projects/{self.PID}/calibrate", json={"page": 10, "corners": corners}, headers=me)
        assert r.status_code == 200, r.text
        lines = {
            ln["id"]: ln
            for ln in client.get(f"/projects/{self.PID}/takeoff", headers=me).json()["lines"]
        }
        slab = lines["ln-slab-on-grade"]
        # The Alberta gate's measured slab is 20.02 m3; the traced outline gives the same.
        assert slab["quantity"] == pytest.approx(20.02, abs=0.1)
        assert slab["basis"]["note"].startswith(STATED_PREFIX)
        assert slab["confidence"] == "inferred"  # never "measured" once a person said it
        client.post(f"/projects/{self.PID}/calibrate", json={"clear": True}, headers=me)

    def test_an_outline_without_any_scale_asks_for_one(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import _sign, app

        client = TestClient(app)
        me = {"x-ecarbon-session": _sign("calib-noscale")}
        # Page 0 is the title sheet: no scale anywhere on it.
        r = client.post(
            f"/projects/{self.PID}/calibrate",
            json={"page": 0, "corners": [[0, 0], [500, 0], [500, 500], [0, 500]]},
            headers=me,
        )
        assert r.status_code == 200
        assert any("Set the scale" in g["message"] for g in r.json()["gaps"])
        client.post(f"/projects/{self.PID}/calibrate", json={"clear": True}, headers=me)
