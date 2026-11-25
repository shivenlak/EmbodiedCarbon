"""The CSV takeoff and the printable report.

Criterion 5 asks for an exportable bill of quantities and a document a builder
could hand a municipality. The property that matters in both is that a number
cannot be separated from its provenance or its module scope.
"""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from ecarbon.api.main import app
from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.fixtures import example_takeoff
from ecarbon.report import CSV_COLUMNS, module_label, report_html, takeoff_csv

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


@pytest.fixture(scope="module")
def pair():
    takeoff = example_takeoff()
    return takeoff, calculate_carbon(takeoff, LocalSnapshotProvider())


class TestModuleLabel:
    def test_a_contiguous_run_is_written_as_a_range(self):
        assert module_label(["A1", "A2", "A3"]) == "A1&ndash;A3"

    def test_a_gap_is_listed_rather_than_implied(self):
        """A1, A3 is not A1-A3; writing it as a range would claim A2."""
        assert module_label(["A1", "A3"]) == "A1, A3"

    def test_a_single_module_stands_alone(self):
        assert module_label(["A1"]) == "A1"

    def test_no_modules_says_so(self):
        assert module_label([]) == "scope unknown"


class TestCsvExport:
    def test_every_declared_column_is_written(self, pair):
        takeoff, carbon = pair
        rows = list(csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon))))
        assert len(rows) == len(takeoff.lines)
        for row in rows:
            assert set(row) == set(CSV_COLUMNS)

    def test_every_row_carries_its_provenance(self, pair):
        """A spreadsheet row that cannot be traced to a sheet is the thing
        this product replaces."""
        takeoff, carbon = pair
        for row in csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon))):
            assert row["sheet"], f"{row['line_id']} exported without a sheet"
            assert row["confidence"] in {"measured", "inferred", "assumed"}

    def test_an_assumed_row_exports_its_assumption(self, pair):
        takeoff, carbon = pair
        for row in csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon))):
            if row["confidence"] == "assumed":
                assert row["assumptions"], f"{row['line_id']} assumed but says nothing"

    def test_an_uncounted_row_exports_the_reason_and_no_figure(self, pair):
        takeoff, carbon = pair
        rows = list(csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon))))
        uncounted = [r for r in rows if r["counted"] == "no"]
        assert uncounted, "the fixture should include an unmatched material"
        for row in uncounted:
            assert row["missing_reason"]
            assert row["kgCO2e"] == ""

    def test_a_counted_row_names_its_factor_and_module_scope(self, pair):
        takeoff, carbon = pair
        for row in csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon))):
            if row["counted"] == "yes":
                assert row["factor_id"] and row["factor_source"]
                assert row["factor_modules"] == "A1+A2+A3"

    def test_quantities_survive_the_round_trip(self, pair):
        takeoff, carbon = pair
        rows = {
            r["line_id"]: r for r in csv.DictReader(io.StringIO(takeoff_csv(takeoff, carbon)))
        }
        for line in takeoff.lines:
            assert float(rows[line.id]["quantity"]) == pytest.approx(line.quantity)

    def test_it_works_without_a_carbon_result(self, pair):
        """The takeoff is exportable before any factor is applied."""
        takeoff, _ = pair
        rows = list(csv.DictReader(io.StringIO(takeoff_csv(takeoff))))
        assert len(rows) == len(takeoff.lines)
        assert all(r["kgCO2e"] == "" for r in rows)


class TestPrintableReport:
    def test_the_scope_appears_with_the_total(self, pair):
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        assert f"{carbon.total_kg_co2e:,.0f}" in page
        assert "A1&ndash;A3" in page
        assert "product stage only" in page

    def test_it_explains_what_the_scope_excludes(self, pair):
        """A reader taking this number into a submission should find it hard
        to misrepresent by accident."""
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        for phrase in ("does not include", "demolition", "not comparable"):
            assert phrase in page

    def test_limits_are_stated_before_the_bill_of_quantities(self, pair):
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        assert page.index("What could not be read") < page.index("Bill of quantities")

    def test_every_line_appears_with_its_citation(self, pair):
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        for line in takeoff.lines:
            if line.provenance.sheet_no:
                assert line.provenance.sheet_no in page

    def test_factor_sources_are_attributed(self, pair):
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        assert "Factor sources" in page
        sources = {c.factor.source for c in carbon.lines if c.factor}
        for source in sources:
            assert source.split("(")[0].strip()[:20] in page

    def test_user_content_is_escaped(self, pair):
        """Project names and notes reach the page; none of them may inject."""
        takeoff, carbon = pair
        takeoff.project.name = '<script>alert("x")</script>'
        page = report_html(takeoff, carbon)
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_open_decisions_are_priced_but_kept_out_of_the_total(self, pair):
        """Cladding left as a placeholder must show up, as a range, not as carbon."""
        from types import SimpleNamespace as NS

        takeoff, carbon = pair
        choice = NS(
            category="Cladding", assembly_tag="W1", drawing_says="placeholder",
            area_m2=120.0, sheet_no="A300", low_kg_co2e=1200.0, high_kg_co2e=5400.0,
            options=[NS(name="Fibre cement", kg_co2e=1200.0), NS(name="Brick", kg_co2e=5400.0)],
        )
        page = report_html(takeoff, carbon, [choice])
        assert "Decisions still open" in page
        assert "1,200&ndash;5,400" in page
        assert "not in the" in page
        assert "Decisions still open" not in report_html(takeoff, carbon)

    def test_it_says_what_the_total_rests_on(self, pair):
        """The share of carbon behind each kind of claim, adding to the whole."""
        import re

        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        assert "Rests on:" in page
        shares = [int(x) for x in re.findall(r"</b> (\d+)%", page.split("Rests on:")[1][:400])]
        assert shares and abs(sum(shares) - 100) <= len(shares)

    def test_it_lists_what_the_total_leaves_out(self, pair):
        """Uncounted rows and deferred layers, gathered where a reader looks."""
        from ecarbon.models import Gap, GapCode, GapSeverity
        from ecarbon.report import _prose

        takeoff, carbon = pair
        takeoff = takeoff.model_copy(deep=True)
        takeoff.gaps.append(Gap(
            code=GapCode.ASSEMBLY_SCHEDULE_MISSING, severity=GapSeverity.WARNING,
            message="R2 layer 5 'PRE FABRICATED ROOF TRUSS' defers to the structural "
                    "drawings, which are not quantified for it, so it is not counted: "
                    "its carbon is missing from the total",
        ))
        page = report_html(takeoff, carbon)
        section = page.split("<h2>Not in the total</h2>")[1].split("<h2>")[0]
        assert "ROOF TRUSS" in section
        for c in carbon.lines:
            if c.kg_co2e is None and c.missing_reason:
                assert _prose(c.missing_reason)[:30] in section

    def test_it_is_a_complete_document(self, pair):
        takeoff, carbon = pair
        page = report_html(takeoff, carbon)
        assert page.startswith("<!doctype html>")
        assert page.rstrip().endswith("</html>")
        # Self-contained: no external stylesheet or script to fetch.
        assert "<link" not in page
        assert "<script" not in page


class TestEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(app)

    def test_csv_downloads_as_a_file(self, client):
        r = client.get("/projects/demo/export.csv")
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
        assert r.headers["content-type"].startswith("text/csv")

    def test_report_serves_html(self, client):
        r = client.get("/projects/demo/report.html")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "Embodied carbon takeoff" in r.text

    def test_an_unknown_project_is_a_404(self, client):
        assert client.get("/projects/nope/export.csv").status_code == 404
        assert client.get("/projects/nope/report.html").status_code == 404


@needs_data
class TestCalculationTrace:
    """UX session, 25 Nov: every kgCO2e figure shows its arithmetic, and the
    CSV alone lets an auditor recompute it."""

    @pytest.mark.parametrize("key", ["AB_Fourplex_01", "AB_ADU_01", "ON_Fourplex_01", "BC_Duplex"])
    def test_every_line_reproduces_its_carbon(self, key):
        from ecarbon.carbon.calc_trace import explain_all
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.takeoff.builder import build_takeoff

        t = build_takeoff(get_design(key))
        c = calculate_carbon(t)
        traces = explain_all(t, c)  # raises if any step list disagrees with the result
        counted = [tr for tr in traces.values() if tr.counted]
        assert counted
        for tr in counted:
            assert tr.steps[-1].unit == "kgCO₂e"
            assert tr.formula.endswith("kgCO2e")

    def test_the_csv_alone_recomputes_every_row(self):
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.takeoff.builder import build_takeoff

        t = build_takeoff(get_design("AB_Fourplex_01"))
        c = calculate_carbon(t)
        rows = list(csv.DictReader(io.StringIO(takeoff_csv(t, c))))
        total = 0.0
        for r in rows:
            if r["counted"] != "yes":
                continue
            kg = float(r["converted_quantity"]) * float(r["waste_factor"]) * float(r["gwp_value"])
            assert kg == pytest.approx(float(r["kgCO2e"]), abs=0.02), r["line_id"]
            total += float(r["kgCO2e"])
        assert total == pytest.approx(c.total_kg_co2e, abs=0.5)

    def test_the_export_carries_a_header_an_auditor_can_cite(self):
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.takeoff.builder import build_takeoff

        t = build_takeoff(get_design("AB_Fourplex_01"))
        text = takeoff_csv(t, calculate_carbon(t), "CA-AB", header=True)
        assert text.startswith("# project,")
        assert "# total kgCO2e," in text and "kg (mass)" in text
