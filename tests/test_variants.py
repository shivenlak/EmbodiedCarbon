"""Unit tests for Step 23: Variants as deltas."""

import pytest

from ecarbon.fixtures import example_takeoff
from ecarbon.models import ElementClass, TakeoffLine, TakeoffResult, Unit, Confidence, Provenance, Basis, BasisSource
from ecarbon.takeoff.variants import compute_variant_delta


def test_variant_delta_identical():
    to1 = example_takeoff()
    to2 = example_takeoff()
    delta = compute_variant_delta(to1, to2)

    assert delta.net_carbon_delta_kg_co2e == 0.0
    assert delta.net_carbon_pct_change == 0.0
    assert delta.modified_lines_count == 0
    assert delta.added_lines_count == 0
    assert delta.removed_lines_count == 0
    assert delta.unchanged_lines_count == len(to1.lines)


def test_variant_delta_modified_and_added():
    to1 = example_takeoff()
    # Create variant with modified quantity on wall and added insulation line
    var_lines = [l.model_copy() for l in to1.lines]
    # Modify line 0
    var_lines[0].quantity = var_lines[0].quantity * 1.2

    # Add a new line
    new_line = TakeoffLine(
        id="ln-variant-extra-cladding",
        element_class=ElementClass.EXTERIOR_WALL,
        quantity=50.0,
        unit=Unit.M2,
        confidence=Confidence.INFERRED,
        assembly_tag="W2",
        material="CMHC_Horizontal Metal Cladding 7/8\"",
        basis=Basis(sources=[BasisSource.SCHEDULE]),
        provenance=Provenance(page=5, sheet_no="A101"),
        description="Variant metal cladding",
    )
    var_lines.append(new_line)

    to2 = to1.model_copy(update={"lines": var_lines})
    delta = compute_variant_delta(to1, to2)

    assert delta.modified_lines_count == 1
    assert delta.added_lines_count == 1
    assert delta.removed_lines_count == 0
    assert delta.net_carbon_delta_kg_co2e > 0.0
    assert delta.net_carbon_pct_change > 0.0
    assert "increase" in delta.summary.lower()
