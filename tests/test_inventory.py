"""Step 6 -- intake and toolchain detection.

The classifier tests run on synthetic probes so they are fast and hermetic.
The tests that touch the catalogue skip when $EC_DATA is absent, so CI and a
teammate without the data can still run the suite.
"""

from __future__ import annotations

import pytest

from ecarbon.intake.inventory import (
    AIA_LAYER_RE,
    PageProbe,
    _decode_pdf_string,
    _split_revit_view_name,
    classify_toolchain,
)
from ecarbon.models import Toolchain


def probe(**kw) -> PageProbe:
    base = dict(page=0, width_in=36.0, height_in=24.0, n_paths=20_000, n_text=400)
    return PageProbe(**{**base, **kw})


class TestToolchainClassification:
    def test_revit_metadata_wins(self):
        p = probe(revit_sheet_no="A101", layer_names=["A-WALL"])
        assert classify_toolchain(p) is Toolchain.REVIT_TAGGED

    def test_aia_layers_when_no_revit_metadata(self):
        assert classify_toolchain(probe(layer_names=["A-WALL", "S-FNDN"])) is Toolchain.AIA_LAYERED

    def test_watermark_only_is_flattened(self):
        # ~Half the catalogue exports flatten layers to a single 'Watermark'.
        assert classify_toolchain(probe(layer_names=["Watermark"])) is Toolchain.FLATTENED

    def test_textless_vector_is_distiller_outlined(self):
        # The 8 NOR sets: millions of path ops, text converted to outlines.
        p = probe(n_paths=4_000_000, n_text=3)
        assert classify_toolchain(p) is Toolchain.DISTILLER_OUTLINED

    def test_textless_beats_revit_metadata(self):
        # Readability constrains everything downstream, so it is decided first.
        p = probe(n_paths=4_000_000, n_text=0, revit_sheet_no="A101")
        assert classify_toolchain(p) is Toolchain.DISTILLER_OUTLINED

    def test_vectorworks_from_producer(self):
        p = probe(layer_names=["Watermark"])
        tc = classify_toolchain(p, producer_tag="Vectorworks Architect 2024")
        assert tc is Toolchain.VECTORWORKS

    def test_image_only_page_is_raster(self):
        assert classify_toolchain(probe(n_paths=4, n_text=0, n_images=12)) is Toolchain.RASTER


class TestReadability:
    def test_textless_page_is_not_readable(self):
        assert not probe(n_text=2).readable

    def test_normal_page_is_readable(self):
        assert probe(n_text=400).readable

    def test_watermark_and_zero_are_not_meaningful_layers(self):
        p = probe(layer_names=["Watermark", "0", "A-WALL"])
        assert p.meaningful_layers == ["A-WALL"]


class TestAiaLayerPattern:
    @pytest.mark.parametrize(
        "name",
        [
            "A-WALL",
            "S-FNDN",
            "G-ANNO-TEXT",
            "A-ANNO-DIMS-25",
            "X-border_$0$G-ANNO-SCHD",  # xref-prefixed, as BC sets are
            "14-24-082 - XFP-4PX-#1-01|A-FLOR",  # xref + job number, as ATL sets are
            "M-HVAC-DUCT-SUPP",
        ],
    )
    def test_matches_real_catalogue_layer_names(self, name):
        assert AIA_LAYER_RE.search(name.upper())

    @pytest.mark.parametrize("name", ["Watermark", "0", "Dimension", "Adobe Fill & Sign"])
    def test_rejects_non_aia_names(self, name):
        assert not AIA_LAYER_RE.search(name.upper())


class TestRevitMetadataParsing:
    def test_splits_sheet_number_from_title(self):
        no, title = _split_revit_view_name("A101 - MAIN FLOOR PLAN - ACCESSIBLE READY")
        assert no == "A101"
        assert title == "MAIN FLOOR PLAN - ACCESSIBLE READY"

    def test_handles_lettered_sheet_numbers(self):
        no, title = _split_revit_view_name("A101a - MAIN FLOOR PLAN - ENHANCED ACCESSIBILITY")
        assert no == "A101a"
        assert title.startswith("MAIN FLOOR PLAN")

    def test_title_without_sheet_number(self):
        no, title = _split_revit_view_name("TITLE SHEET")
        assert no is None
        assert title == "TITLE SHEET"

    def test_none_is_safe(self):
        assert _split_revit_view_name(None) == (None, None)

    def test_decodes_utf16_be_with_bom(self):
        raw = "(" + "\xfe\xff" + "".join("\x00" + c for c in "A010") + ")"
        assert _decode_pdf_string(raw) == "A010"

    def test_strips_nuls_from_plain_string(self):
        assert _decode_pdf_string("(A\x000\x001\x000)") == "A010"

    def test_empty_becomes_none(self):
        assert _decode_pdf_string("()") is None
        assert _decode_pdf_string(None) is None


# -- tests that need the catalogue -----------------------------------------

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


@needs_data
class TestAgainstRealCatalogue:
    def test_alberta_fourplex_matches_research(self):
        """RESEARCH.md §2: AB_Fourplex_01 is 46 pages, ~740k path ops."""
        from ecarbon.intake import inventory

        d = get_design("AB_Fourplex_01")
        sheets, _, _ = inventory(d.drawings_pdf)
        assert len(sheets) == 46
        assert sum(s.n_paths for s in sheets) > 400_000
        assert all(s.width_in in (24.0, 36.0) for s in sheets)

    def test_revit_sheets_are_identified_for_free(self):
        from ecarbon.intake import inventory

        sheets, _, _ = inventory(get_design("AB_Fourplex_01").drawings_pdf)
        tagged = [s for s in sheets if s.toolchain is Toolchain.REVIT_TAGGED]
        assert len(tagged) >= 10, "Revit page metadata should classify the arch sheets"
        assert any(s.sheet_no == "A003" for s in tagged)

    def test_nor_set_is_detected_as_textless(self):
        """The 8 NOR sets must be flagged, not guessed at."""
        from ecarbon.intake import inventory, set_toolchain

        d = get_design("NOR_Fourplex_Municipal")
        sheets, _, _ = inventory(d.drawings_pdf)
        assert set_toolchain(sheets) is Toolchain.DISTILLER_OUTLINED
        assert sum(1 for s in sheets if not s.readable) > len(sheets) * 0.8


class TestLowPathReadablePages:
    """A schedule or spec sheet is mostly type with very few path operators.
    It must not fall through to UNKNOWN (ON_ADU_01 regression)."""

    def test_text_heavy_low_path_page_is_classified(self):
        p = probe(n_paths=171, n_text=353, n_images=2)
        assert classify_toolchain(p) is Toolchain.FLATTENED

    def test_text_heavy_low_path_page_with_layers(self):
        p = probe(n_paths=171, n_text=353, layer_names=["G-ANNO-SCHD"])
        assert classify_toolchain(p) is Toolchain.AIA_LAYERED

    def test_empty_page_is_unknown(self):
        assert classify_toolchain(probe(n_paths=2, n_text=0, n_images=0)) is Toolchain.UNKNOWN

    def test_textless_page_inside_a_readable_set(self):
        """ON/BC/SKMB sets contain individual outlined pages, not just NOR."""
        p = probe(n_paths=242_979, n_text=0, n_images=2)
        assert classify_toolchain(p) is Toolchain.DISTILLER_OUTLINED


class TestGapReport:
    def test_outlined_pages_are_reported_with_consequence(self):
        from ecarbon.intake import readability_gaps
        from ecarbon.models import GapCode, GapSeverity, SheetInfo

        sheets = [
            SheetInfo(page=i, readable=False, toolchain=Toolchain.DISTILLER_OUTLINED)
            for i in range(30)
        ]
        gaps = readability_gaps(sheets)
        assert gaps and gaps[0].code is GapCode.PAGE_TEXT_UNREADABLE
        # Most of the set is affected, so this blocks rather than warns.
        assert gaps[0].severity is GapSeverity.BLOCKING
        assert "inferred" in gaps[0].message

    def test_a_couple_of_outlined_pages_only_warns(self):
        from ecarbon.intake import readability_gaps
        from ecarbon.models import GapSeverity, SheetInfo

        sheets = [SheetInfo(page=i, readable=True, toolchain=Toolchain.FLATTENED) for i in range(20)]
        sheets += [
            SheetInfo(page=i, readable=False, toolchain=Toolchain.DISTILLER_OUTLINED)
            for i in (20, 21)
        ]
        gaps = [g for g in readability_gaps(sheets) if g.severity is GapSeverity.WARNING]
        assert gaps

    def test_cover_page_is_not_reported_as_a_problem(self):
        from ecarbon.intake import readability_gaps
        from ecarbon.models import SheetInfo

        sheets = [SheetInfo(page=0, readable=False, toolchain=Toolchain.RASTER)]
        assert readability_gaps(sheets) == []

    def test_missing_required_sheet_types_block(self):
        from ecarbon.intake import coverage_gaps
        from ecarbon.models import GapSeverity, SheetInfo

        gaps = coverage_gaps([SheetInfo(page=0, readable=True)])
        assert len(gaps) == 6
        assert all(g.severity is GapSeverity.BLOCKING for g in gaps)
        assert any("assembly schedule" in g.message for g in gaps)
