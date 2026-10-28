"""Click-to-trace: a line resolves to the region of the sheet it came from.

The feature's value is entirely in being right. A highlight that lands on the
wrong sheet is worse than no highlight, because it manufactures confidence --
so the tests check that the page and the sheet number agree, and that a region
that cannot be located says so instead of guessing.
"""

from __future__ import annotations

import pytest

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


def takeoff_for(key: str):
    from ecarbon.bench.bpr import parse_bpr
    from ecarbon.models import ProjectFacts
    from ecarbon.takeoff.builder import build_takeoff

    design = get_design(key)
    bpr = parse_bpr(str(design.bpr[0])) if design.bpr else None
    return design, build_takeoff(
        design,
        ProjectFacts(
            name=key,
            gfa_m2=bpr.best_gfa_m2 if bpr else None,
            gfa_basis="gross",
            storeys=bpr.storeys if bpr else None,
            units=bpr.units if bpr else None,
        ),
    )


@needs_data
class TestProvenanceIsSelfConsistent:
    """The bug that made this necessary: `_prov` took the footprint's page for
    every line, so the slab named S201 and carried page 10, which is A101. The
    sheet number read correctly in a table while the page pointed elsewhere,
    and nothing cross-checked the two."""

    @pytest.mark.parametrize(
        "key", ["AB_Fourplex_01", "AB_Sixplex", "AB_Rowhouse_02", "AB_ADU_02"]
    )
    def test_every_line_page_matches_the_sheet_it_names(self, key):
        from ecarbon.intake import inventory

        design, takeoff = takeoff_for(key)
        sheets, _, _ = inventory(design.drawings_pdf)
        page_of = {s.sheet_no.upper(): s.page for s in sheets if s.sheet_no}
        for line in takeoff.lines:
            named = (line.provenance.sheet_no or "").upper()
            if named in page_of:
                assert line.provenance.page == page_of[named], (
                    f"{line.id} names {named} but points at page "
                    f"{line.provenance.page}"
                )

    def test_the_slab_points_at_the_structural_sheet(self):
        design, takeoff = takeoff_for("AB_Fourplex_01")
        slab = takeoff.line("ln-slab-on-grade")
        assert slab.provenance.sheet_no == "S201"
        assert slab.provenance.page == 24


@needs_data
class TestTrace:
    @pytest.fixture(scope="class")
    def built(self):
        return takeoff_for("AB_Fourplex_01")

    def test_most_lines_resolve_to_a_region(self, built):
        from ecarbon.trace import trace_line

        design, takeoff = built
        located = sum(
            1
            for ln in takeoff.lines
            if any(r.located for r in trace_line(design, takeoff, ln.id))
        )
        assert located >= len(takeoff.lines) - 2

    def test_a_region_lands_on_the_page_it_names(self, built):
        import pymupdf

        design, takeoff = built
        from ecarbon.trace import trace_line

        doc = pymupdf.open(design.drawings_pdf)
        try:
            for ln in takeoff.lines:
                for region in trace_line(design, takeoff, ln.id):
                    assert 0 <= region.page < doc.page_count
                    page = doc[region.page]
                    for x0, y0, x1, y1 in region.rects:
                        assert x1 > x0 and y1 > y0, f"{ln.id} has an empty rect"
                        assert -1 <= x0 and x1 <= page.rect.width + 1
                        assert -1 <= y0 and y1 <= page.rect.height + 1
        finally:
            doc.close()

    def test_partitions_trace_to_the_walls_measured_on_every_storey(self, built):
        from ecarbon.trace import trace_line

        design, takeoff = built
        regions = trace_line(design, takeoff, "ln-interior-partition-p1-l0")
        assert len(regions) >= 2, "partitions are measured on each storey"
        assert all(r.kind == "measured_geometry" for r in regions)
        # One rectangle per wall counted, so the highlight is the measurement.
        assert sum(len(r.rects) for r in regions) == sum(
            r.n_walls for r in __import__(
                "ecarbon.geometry.partitions", fromlist=["partitions_for"]
            ).partitions_for(design).runs
        )

    def test_an_unlocatable_region_says_so_rather_than_guessing(self, built):
        from ecarbon.trace import trace_line

        design, takeoff = built
        for ln in takeoff.lines:
            for region in trace_line(design, takeoff, ln.id):
                if region.kind == "sheet_only":
                    assert region.rects == []
                    assert "not" in region.note or "could not" in region.note

    def test_an_unknown_line_traces_to_nothing(self, built):
        from ecarbon.trace import trace_line

        design, takeoff = built
        assert trace_line(design, takeoff, "ln-does-not-exist") == []

    def test_the_rendered_page_is_a_png(self, built):
        from ecarbon.trace import render_page

        design, _ = built
        png = render_page(design, 10, [(100.0, 100.0, 200.0, 140.0)], dpi=50)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


class TestTraceApi:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import app

        return TestClient(app)

    def test_tracing_without_drawings_explains_itself(self, client):
        """The demo project is fixture-backed because the catalogue cannot be
        committed, so it has no sheets to show. That must be a clear 404, not
        a 500."""
        takeoff = client.get("/projects/demo/takeoff").json()
        line_id = takeoff["lines"][0]["id"]
        resp = client.get(f"/projects/demo/trace/{line_id}")
        assert resp.status_code == 404
        assert "nothing to trace" in resp.json()["detail"]

    def test_an_unknown_line_is_404(self, client):
        resp = client.get("/projects/demo/trace/ln-nope")
        assert resp.status_code == 404
