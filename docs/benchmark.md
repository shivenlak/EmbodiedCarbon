# Accuracy benchmark

Every number here is printed by a script in `scripts/`, named beside it. Run
any of them against the public CMHC Housing Design Catalogue and you should
get the same figures; if you don't, that's a bug worth reporting. Worst cases
are published next to medians, because a median alone hides the designs where
this does badly, and those are the ones a builder needs to know about.

Generated 2026-10-25 against 53 drawing sets / 52 packages.

---

## Read this first: the headline figure is a best case

    python scripts/run_pipeline.py

Running the whole pipeline on all 53 sets, no code changes, nothing tuned per
design:

| | Result |
|---|---|
| Crashed | **0 of 53** |
| Produced quantities | 45 |
| Produced none **and reported why** | 8 (the textless NOR sets) |
| Seconds per design | median **13.0**, worst 24.7 |
| Element coverage | median **44%**, best 91%, worst 0% |
| Designs reaching 80% coverage | **6 of 45** |

| Region | n | Coverage, median | Best | Intensity kgCO₂e/m², median |
|---|---|---|---|---|
| **Alberta** | 7 | **91%** | 91% | 132.5 |
| Quebec | 7 | 66% | 66% | 116.1 |
| British Columbia | 7 | **59%** | 59% | 30.8 |
| Atlantic | 9 | **42%** | 57% | 33.8 |
| Ontario | 7 | **42%** | 75% | 57.3 |
| SKMB | 7 | 9% | 9% | 8.3 |
| NOR | 9 | — | — | — |

**Alberta is the region this was developed against, and it shows.** Six of its
seven sets reach 91% element coverage at an intensity of 122–166 kgCO₂e/m²,
which is a plausible product-stage figure. Elsewhere coverage runs 10–48% and
the intensity falls to 8–42 kgCO₂e/m² — not because those buildings are
lighter, but because a partial bill of quantities produces a partial total.
Intensity tracks coverage almost exactly, which is the expected signature and
also the reason every total in this system is reported with the share of the
building it reaches.

So: where a figure below is quoted for AB_Fourplex_01 — 91% coverage, 37,536
kgCO₂e, 122.7 kgCO₂e/m² — read it as **the best case on the development
region**, not as typical. The median design gets 44%, and only five of 45 reach 80%.

What separates them is whether two sheets parse. A design reaches 80%+ only
when both its assemblies schedule and its openings schedule are readable:
Alberta's are, Ontario's multiplexes have neither, and BC parses openings but
loses its exterior wall assembly to the plausibility gate.

---

## What is measured against what

Three independent references, each with real limits:

| Reference | What it gives | Where it is weak |
|---|---|---|
| **IFC models** (53, IFC2X3) | element geometry, material layer sets | 52 of 53 contain **no** pre-computed quantities, so ours is a geometry engine against theirs; 7 SKMB models are pure B-rep with no semantic element types at all |
| **HOT2000 files** (45) | thermal envelope areas, slab perimeter | thermal, not structural — no partitions, no quantities |
| **Building Performance Reports** (73) | published whole-life carbon, floor areas, storeys, units | scope is **A1–A5 + B4–B5 + C2–C4**, so it is an upper bound on our A1–A3, never a like-for-like comparison |

The catalogue's own `List of Drawings` PDFs provide labelled sheet-identity
truth for 51 of 52 packages, which is where the Stage 1 figures come from.

**The reference is not perfect truth.** Cross-checking IFC against HOT2000 on
AB_Fourplex_01 gives exterior wall areas of 287.6 m² and 290.6 m² — 1.0% apart
from two models of the same building. Published work on construction takeoff
reports professional human estimators agreeing with a reference within ±25% on
about 88% of line items. Treat ±10% on the drivers as a good result, not a
disappointment.

---

## Stage 1 — Drawing intake and sheet identity

    python scripts/score_sheets.py

| | Result | Bar |
|---|---|---|
| Pages scored | **1,465** | |
| Sheet-number match | **97.9%** | 90% ✅ |
| Sheet-type match | **95.1%** | 85% ✅ |
| Textless sets that report the gap | **8 of 8** | all ✅ |

By detected export toolchain, median sheet-number match:

| Toolchain | n | Median | Worst |
|---|---|---|---|
| `aia_layered` | 19 | 100% | 90% |
| `flattened` | 23 | 100% | 91% |
| `revit_tagged` | 1 | 100% | 100% |
| `vectorworks` | 1 | 100% | 100% |
| `distiller_outlined` | 8 | **0%** | 0% |

The 0% row is the important one. Those eight NOR sets were exported through
Acrobat Distiller with **all text converted to vector outlines** — there is no
text on any sheet to read, which is why their path counts are 2.7–4.7 million,
four to seven times every other set. We score 0% on them and all eight report
that gap rather than guessing, which is the behaviour the row is meant to show.

---

## Stage 1 — Scale calibration

    python scripts/score_scale.py

| | Result |
|---|---|
| Independent scale sources agreeing within 1% | **43 of 45** |
| Short axis vs IFC: median error | **0.00%** |
| Short axis within 2% | **36 of 38** |
| Short axis worst | 37.0% |
| Long axis: median error | **0.00%** |
| Long axis within 2% | 33 of 38 |

The long axis misses more often than the short, and that is a limit of the
*check* rather than of the scale: on a building with wings or a courtyard, no
single dimension label equals the axis-aligned envelope, so the comparison is
measuring different things at both ends.

Not scoreable: 8 designs with no readable scale (the textless sets), 7 whose
IFC geometry is too degraded to compare against.

---

## Stage 2 — Building footprint

    python scripts/score_footprint.py

| | Result |
|---|---|
| Designs scored | **38** |
| Median error | **3.3%** |
| Within 5% | 24 / 38 |
| Within 10% | **32 / 38** |
| Within 25% | 33 / 38 |
| Worst | **63.3%** |

Excluded and why: 8 designs where no footprint could be established at all and
the pipeline says so rather than producing a number, and 7 whose IFC is
unusable as a reference.

---

## Stage 2 — Assemblies, and what we refuse to read

    python scripts/score_assemblies.py

The assemblies schedule turns an element area into materials, which is what
takes a wall from "309 m² of wall" to cladding, sheathing, insulation and
gypsum.

| Region | Designs with a trustworthy schedule |
|---|---|
| Alberta | **7 / 7** |
| British Columbia | **7 / 7** |
| Quebec | **7 / 7** |
| Atlantic | **8 / 9** |
| Ontario | **7 / 7** |
| NOR | 0 / 9 |
| SKMB | 0 / 7 |
| **Total** | **38 / 53** |

**413 assemblies kept, 172 refused.** The refusals matter as much as the
parses. Reading this sheet across firms sometimes merges adjacent blocks or
starts one on a layer row, and the result is structurally wrong while looking
completely ordinary — a 47-layer, 1.6 m "VAULTED ROOF" on BC_Duplex, and
assemblies *named* `GYPSUM BOARD` on ATL_Sixplex. Anything past 15 layers or
800 mm of built depth, or named after one of its own materials, is reported
unreadable rather than used, because a wrong build-up produces wrong
quantities silently while a refusal produces a gap that says so.

| Why an assembly was refused | n |
|---|---|
| its name is one of its own layers | 99 |
| more layers than an assembly has | 20 |
| implausible built depth | 7 |
| no layer states a thickness, or other | 46 |

### Built depth against the IFC's own layer sets

Comparing the depth we read off the drawing against the depth the IFC models,
on every assembly where both exist:

| | Result |
|---|---|
| Assemblies compared | **195** |
| Median error | **15.2%** |
| Mean error | 28.4% |
| Exact (<0.5%) | **47 / 195** |
| Within 10% | **86 / 195** |
| Worst | 1171.8% |

**Reading more schedules cost per-assembly precision, and the number that
matters is the one that did not move.** Across every change in this
catalogue's history, `exact` has held at **47** and `within 10%` at **86**: no
reading that was once good has degraded. What grew is the denominator — the
comparison set went from 148 assemblies to 195 and designs from 31 to 38 — and
the assemblies added are the hard ones: dotted BC tags, glyph-ID Ontario cells,
Atlantic tables whose name column sits 34 pt from its header. So the median
rose from 5.8% to 15.2% by dilution, not by regression.

Three causes account for most of the remaining spread, and two of them are the
reference rather than the measurement:

- **The IFC lumps foundations.** `F1 SLAB ON GRADE` reads 76 mm from the
  drawings against 356 mm in the model, the same defect as Alberta's single
  454 mm layer where the drawings specify a 130 mm slab over insulation and
  granular fill.
- **Joists are counted on different sheets.** `F2 WOOD FRAMED FLOOR` reads
  70 mm because the drawings defer the joist depth to structural, which we
  honour; the IFC includes it, at 393 mm.
- **Some IFC layer sets are a single membrane.** The 1171% worst case is a
  cathedral roof we read at 524 mm against an IFC layer set of 41 mm.

The one genuine parse fault found in this group has been fixed: one-layer
blocks whose names are plainly layers — `WOOD STUD FRAMING @ 1'-4"`, `BATT
INSULATION IN CAVITY`, `WOOD DECKING` — were passing the name filter because it
lacked those words. Tightening it removed four bad comparisons and moved the
median from 16.3% to 15.2%. The tightening needed its own correction: an
end-anchored `STUD FRAMING` pattern refused Quebec's genuine `W1`, `DOUBLE
BRICK MASONRY W/ WOOD STUD FRAMING`, so a spacing callout is now required —
a layer states its spacing, a composite assembly name does not.

Excluded: 14 tags the IFC models with more than one build-up, where there is
no single depth to compare against. AB_Fourplex_01's P2 exists as both a
165 mm plain partition and a 201 mm rated one; our parse is the rated version
and matches it exactly, so scoring against the nearest variant would flatter
us and against the first would penalise us by 22%. Neither is a measurement.

**Two notes on honesty here.** First, an earlier version of this document
quoted "P1, P2 and P3 match the IFC exactly" — true, but those were three
assemblies picked from nine, which is selective reporting of exactly the kind
this benchmark exists to avoid. The distribution above is all of them.

Second, these numbers were wrong until the harness was fixed: **every BC model
declares its length unit as FOOT** while Alberta and Quebec use millimetres,
and reading `LayerThickness` raw scored a correct 172 mm wall as 34,300% in
error against a 0.50 ft layer set that is really 152.4 mm. Correcting it moved
the median from 22.1% to 5.8% and the exact count from 34 to 48. Geometry read
through ifcopenshell's engine was never affected, because it arrives in metres
regardless of the file's units — so the footprint and scale figures above
stand unchanged.

Where the two sources disagree the drawing is sometimes the better one. The
IFC lumps AB_Fourplex_01's whole foundation into a single 454 mm layer where
the drawings specify a 130 mm slab over sub-slab insulation and granular base
(39% apart, and the IFC overstates foundation concrete by 1.93× on this
design); our R2 roof excludes the truss because the drawing defers it to the
structural sheets while the IFC includes its full depth (44% apart); and the
IFC generalises W2's framing to `CMHC_Wood Framing` where the drawing says
`METAL STUD FRAMING` — W2 is the non-combustible rated wall, so it is steel.

**SKMB publishes no assemblies schedule at all** — its packages carry only
`S002 TYPICAL DETAILS`. That is a gap in the source documents rather than in
this software, and no amount of parsing closes it.

Ontario's schedules now read (7 of 7, up from 2) after a glyph-ID repair
scoped to this module. Their sheets are drawn rotated a quarter turn and
encoded under a single 0x1D shift, and the two cell kinds the global text
repair refuses — thicknesses, because `PP` is `mm` and contains letters, and
tags, because `W1` is too short to validate — are recovered only when the
shifted result is a real numeric thickness or a well-formed tag. The global
guards are untouched: sheet identification still measures 97.9% and 95.1%.

---

## Stage 2 — Windows and doors

    python scripts/score_openings.py

Counts come from two sheets at once: size per tag from the openings schedule,
instance count from the tags written on the floor plans.

| | Windows | Doors |
|---|---|---|
| Designs scored | 43 | 43 |
| Median error | **5.4%** | **1.4%** |
| Mean error | 17.5% | 14.1% |
| Within 10% | 26 / 43 | **33 / 43** |
| Within 25% | 34 / 43 | 34 / 43 |
| Worst | 100% | 66.7% |

Quebec is exact on all seven of its designs. AB_Fourplex_01 gives **40 doors
against the IFC's 40**.

**The mean is dragged up by one cluster, and naming it is most of the value
here.** Every stacked townhouse comes in at −66.7% on doors — exactly one
third, not a scatter. The cause is not the de-duplication of variant sheets:
those designs number their storeys cleanly and all are counted. It is that the
drawings depict **one unit of a repeated block** and leave the reader to know
there are more.

That is checkable rather than a typology guess, because the measured footprint
and the stated floor area disagree in exactly those cases:

| Design | GFA ÷ (footprint × storeys) | Door error |
|---|---|---|
| AB_Fourplex_01 | 0.99 | 0.0% |
| QC_Sixplex | 0.98 | 0.0% |
| skmb_rowhouse | 0.72 | −66.7% |
| ON_Stacked_Townhouse_01 | 0.51 | −66.7% |

The takeoff raises a blocking gap when the ratio departs from 1 by more than
15%, naming the lines counted off the plans. **No multiplier is applied.**
Guessing one would scale every count on an assumption, and a wrong multiplier
is worse than a stated shortfall.

It catches 4 of the 6 undercounting designs. `ATL_Stacked_Townhouse_01` has no
confident footprint, so the ratio cannot be formed, though a blocking geometry
gap already covers it. `AB_Rowhouse_02` sits at 0.91 and is **not** flagged,
yet its doors are 61% short while its windows are exact — so its cause is
something other than plan extent, and this check does not explain it.

---

## Stage 3 — Carbon

Not an accuracy measurement, because there is no A1–A3 reference to measure
against: the published CMHC figures are A1–A5 + B4–B5 + C2–C4 and summing
across those scopes is the error the challenge tests for. What can be checked
is discipline.

| | |
|---|---|
| Factors in the store | **18**, none hardcoded in code |
| Each carrying | source, source id, declared unit, density, module scope, geography, validity, data type, uncertainty, attribution |
| Module scopes present | A1–A3 only |
| Summing across scopes | **raises**, never silently totals |
| Unmatched materials | visible rows with a stated reason, excluded from the total |

AB_Fourplex_01 end to end: **37,536 kg CO₂e A1–A3 at 122.7 kg/m²**, from 17
bill-of-quantities lines covering **91%** of the building's embodied carbon by
element. The published whole-life figure for the same building is 162,043 kg
CO₂e, of which A1–A5 is 107,000 — our product-stage subset sits below that
ceiling, as it must.

Two factor values in the inherited store were wrong against the prescribed
guide and were corrected: GUL + 40% fly ash at 25 MPa read 142 where the guide
prints **175** (which had overstated the flagship substitution as a 48.5% cut
rather than **36.6%**), and a "Portland GU, 20 MPa" row did not exist in the
guide at all, whose lowest strength is 25 MPa.

---

## What this does not measure

Stated plainly, because a benchmark that only reports its wins is not a
benchmark:

- **No reference takeoff exists.** CMHC's published Construction Cost
  Estimates contain quantity take-offs but are not in the data package, so
  every figure above is measured against geometry we derived ourselves from
  the IFCs, not against a quantity surveyor's bill.
- **Interior partitions are not quantified**, and this was tried properly
  rather than assumed impossible. The approach was sound on paper: the
  assemblies schedule states each partition's built depth (P1 121 mm, P2
  201 mm, P3 235 mm, P5 118 mm), a wall is two parallel lines separated by its
  thickness, and furniture and door swings are not. Measured against partition
  run lengths taken from the IFC geometry:

  | Design | Detected | IFC | |
  |---|---|---|---|
  | AB_Fourplex_01 | 111.8 m | 158.8 m | −30% |
  | AB_Fourplex_02 | 180.9 m | 238.6 m | −24% |
  | AB_Sixplex | 180.1 m | 262.2 m | −31% |
  | AB_Rowhouse_02 | 158.0 m | 213.4 m | −26% |
  | QC_Fourplex_01 | 47.8 m | 180.7 m | −74% |
  | QC_Sixplex | 152.1 m | 308.0 m | −51% |
  | BC_Duplex | 63.8 m | 128.9 m | −50% |

  Alberta is consistently about 28% low, which looked like a fixable bias —
  short wall stubs below the minimum segment length, or pairs rejected for
  partial overlap. It is not: relaxing the minimum length from 400 mm to
  100 mm, the overlap requirement from 0.6 to 0.25 and the thickness tolerance
  from 8 mm to 14 mm moves Alberta from −30% to −33% and Quebec not at all.
  The missing partitions are not short — they are not in the wall lineweight
  group at all. Searching every group instead overshoots by +350%, because
  poché hatching, cabinetry and door swings also produce parallel pairs at
  partition spacings.

  So the detection finds roughly 70% of partitions on the region it was built
  against and 25–50% elsewhere, with no parameter that improves both. A line
  wrong by up to three-fold on 8% of a building's carbon is worse than a
  stated gap, so none is produced. What would fix it is classifying wall
  linework directly rather than inferring it from lineweight — the ~20
  layer-labelled sets in this catalogue carry `A-WALL` layer names and could
  supply training labels for exactly that.
- **Cladding and roofing carry no carbon**, because CMHC leaves them
  deliberately unspecified as placeholders. Defaulting them would move about
  12% of a home's embodied carbon on a choice nobody made.
- **A4–A5 are architecture only**, as the scope permits — the extension points
  exist, the modules are not implemented.
- **Held-out discipline is imperfect.** These numbers are measured across the
  whole catalogue rather than a strictly untouched slice, so treat them as
  development figures. The honest test is Landmark's own sets, which we have
  never seen.
