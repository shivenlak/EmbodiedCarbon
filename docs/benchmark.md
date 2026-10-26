# Accuracy benchmark

Every number here is printed by a script in `scripts/`, named beside it. Run
any of them against the public CMHC Housing Design Catalogue and you should
get the same figures; if you don't, that's a bug worth reporting. Worst cases
are published next to medians, because a median alone hides the designs where
this does badly, and those are the ones a builder needs to know about.

Generated 2026-10-26 against 53 drawing sets / 52 packages.

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
| Seconds per design | median **13.2**, worst 25.4 |
| Element coverage | median **52%**, best 100%, worst 0% |
| Designs reaching 80% coverage | **7 of 45** |

| Region | n | Coverage, median | Best | Intensity kgCO₂e/m², median |
|---|---|---|---|---|
| **Alberta** | 7 | **100%** | 100% | 174.8 |
| Quebec | 7 | 74% | 74% | 132.9 |
| British Columbia | 7 | **67%** | 67% | 41.2 |
| Atlantic | 9 | **44%** | 65% | 33.8 |
| Ontario | 7 | **29%** | 83% | 52.8 |
| SKMB | 7 | 9% | 9% | 8.3 |
| NOR | 9 (**1** scored) | 9% | 9% | 1.0 |

NOR's single figure is the one set of nine whose text survived export. The
other eight are vectorised outlines, produce nothing, and say why — so the
45 designs that produced quantities are 7 + 7 + 7 + 9 + 7 + 7 + 1.

**Alberta is the region this was developed against, and it shows.** Six of its
seven sets now reach **100%** element coverage — every class the building has
is counted — at an intensity of 150–186 kgCO₂e/m², a plausible product-stage
figure. The seventh, AB_ADU_01, sits at 53%: a single-storey plan yields fewer
than two floor datums, so there is no storey height and therefore no wall,
floor or partition area. Elsewhere coverage runs 9–83% and the intensity falls
to 1–53 kgCO₂e/m² — not because those buildings are lighter, but because a
partial bill of quantities produces a partial total.
Intensity tracks coverage almost exactly, which is the expected signature and
also the reason every total in this system is reported with the share of the
building it reaches.

So: where a figure below is quoted for AB_Fourplex_01 — 100% coverage, 48,613
kgCO₂e, 158.9 kgCO₂e/m² — read it as **the best case on the development
region**, not as typical. The median design gets **52%**, and only **7 of 45**
reach 80%.

What separates them is whether two sheets parse. A design reaches 80%+ only
when both its assemblies schedule and its openings schedule are readable:
Alberta's are, Ontario's multiplexes have neither, and BC parses openings but
loses its exterior wall assembly to the plausibility gate.

**Ontario moved the wrong way this round** — 42% → 29% — while Alberta went to
100%. That regression is real, is not explained yet, and is described under
"What this does not measure" rather than netted off against the gain.

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
| Median error | **4.0%** | **0.0%** |
| Mean error | 15.2% | 12.5% |
| Within 10% | 27 / 43 | **34 / 43** |
| Within 25% | 35 / 43 | 35 / 43 |
| Worst | 100% | 66.7% |

Quebec is exact on all seven of its designs. AB_Fourplex_01 gives **40 doors
against the IFC's 40**.

**The median door count is exact**, and it got there by fixing how a storey is
identified rather than by anything to do with doors. `AB_ADU_01` numbers its
two accessibility options `A101` and `A102` -- they look like two storeys and
are both the main floor, so that building was counted twice and read 15 doors
against the 9 its model contains. Neither available signal fixes this alone,
and each repairs the other's failure: sheet numbers catch the usual `A101` /
`A101a` pairing but miss `A101` / `A102`, while title heads catch that pair and
break five designs that title an option "ACCESSIBLE-READY MAIN FLOOR PLAN",
whose head is "ACCESSIBLE" -- measured, that alone took ON_Fourplex_02's doors
from exactly right to 44% over. Two sheets are now one storey when **either**
signal agrees, closed transitively, which moved windows 5.4% -> 4.0% and doors
1.4% -> 0.0%.

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

## Stage 2 — Interior partitions

    python -m pytest tests/test_partitions.py

The only quantity here measured off the linework rather than read from a
schedule. Partition run length is measured at the wall lineweight and paired
against the depths the assemblies schedule states, then checked against the
partition walls in each reference model.

| Design | Measured | IFC | Error |
|---|---|---|---|
| AB_ADU_01 | 38.0 m | 36.3 m | +4.8% |
| AB_ADU_02 | 68.2 m | 35.5 m | **+92.2%** |
| AB_Fourplex_01 | 169.7 m | 158.8 m | +6.9% |
| AB_Fourplex_02 | 236.9 m | 238.6 m | −0.7% |
| AB_Rowhouse_01 | 161.0 m | 151.2 m | +6.5% |
| AB_Rowhouse_02 | 225.6 m | 213.4 m | +5.7% |
| AB_Sixplex | 253.6 m | 262.2 m | −3.3% |

**Median 5.7%, six of seven within 10%, worst +92%.** AB_ADU_02 over-detects:
it is a small dwelling whose cabinetry sits at spacings close to a partition's.
Because this is a real measurement rather than an estimate the lines are
labelled `inferred`, not `assumed` — but the uncertainty travels with them, the
carbon total is reported with and without them, and the run length can be
overridden.

**Four approaches failed first, and they are published in the gap report** on
the principle that a reader deciding whether to trust the least certain line
deserves to know it was hard to get:

| Approach | Error |
|---|---|
| Pair search across every lineweight | +350% |
| Wall lineweight, segments ≥ 1 m | −30% |
| Seeded from partition tags, unmerged | −66% |
| Merged runs, no lineweight restriction | +306% |

What found it was a spacing histogram rather than a fifth idea. The
wall-lineweight group's neighbour spacings on AB_Fourplex_01 read
`[(121, 20), (36, 6), (2, 5), (241, 3)]`, and **121 mm is exactly P1's stated
depth**. The partitions had been in that group the whole time: the 1 m minimum
segment length from the second attempt had deleted them, because that group
holds 297 segments under 250 mm — partition faces break at every door, jamb and
intersection.

**Known weakness, unresolved.** AB_Fourplex_01's `W1` exterior wall is 235 mm
and its `P3` demising wall is also 235 mm, so depth alone cannot separate an
exterior run from a partition. A perimeter-exclusion filter was written and
measured; it changed nothing on all seven designs, because the wall-segment
pool includes grid and section linework so its extents are far wider than the
building. The filter was removed rather than kept as a protection it does not
provide. Whether exterior runs are contaminating this figure is not settled;
the arithmetic argues against it (this building's perimeter is 58 m, so two
storeys of exterior wall is ~116 m, and counting it would put the measurement
near 275 m rather than 169.7 m) but that is an argument, not a measurement.

---

## Criterion 2 — Traceability

    python -m pytest tests/test_trace.py

Every line carries the sheet and detail it came from; 19 of 20 on
AB_Fourplex_01 also resolve to a region of that sheet. The strength of each
trace is stated rather than implied, because these are different claims:

| Kind | Meaning | Lines |
|---|---|---|
| `measured_geometry` | The outlined rectangles **are** the measurement | 6 |
| `schedule_row` | The text the figure was read from | 13 |
| `sheet_only` | Right sheet, region not located — **nothing highlighted** | 1 |

Interior partitions keep one rectangle per wall counted, so their highlight is
the measurement itself rather than a picture near it.

**Building this found a provenance bug that it would otherwise have put on
screen.** The builder took the footprint's page for every line regardless of
the sheet the caller named, so the slab named `S201` — correct, and asserted by
the Alberta regression gate — while carrying page 10, which is `A101`. Five
foundation and level lines pointed at the wrong drawing while reading correctly
in a table, because nothing cross-checked that a line's page and its sheet
number referred to the same sheet. A test now asserts they agree for every line
across four designs.

---

## Stage 3 — Carbon

Not an accuracy measurement, because there is no A1–A3 reference to measure
against: the published CMHC figures are A1–A5 + B4–B5 + C2–C4 and summing
across those scopes is the error the challenge tests for. What can be checked
is discipline.

| | |
|---|---|
| Factors in the store | **20**, none hardcoded in code |
| Each carrying | source, source id, declared unit, density, module scope, geography, validity, data type, uncertainty, attribution |
| Module scopes present | A1–A3 only |
| Summing across scopes | **raises**, never silently totals |
| Unmatched materials | visible rows with a stated reason, excluded from the total |

AB_Fourplex_01 end to end: **48,613 kg CO₂e A1–A3 at 158.9 kg/m²**, from 20
bill-of-quantities lines covering **100%** of the building's embodied carbon by
element. Excluding the inferred interior partitions it is **37,536 kg CO₂e**,
and both are reported because the partition run is measured off the linework
rather than stated by a schedule. The published whole-life figure for the same
building is 162,043 kg CO₂e, of which A1–A5 is 107,000 — our product-stage
subset sits below that ceiling, as it must.

Two factor values in the inherited store were wrong against the prescribed
guide and were corrected: GUL + 40% fly ash at 25 MPa read 142 where the guide
prints **175** (which had overstated that substitution as a 48.5% cut rather
than **36.6%**), and a "Portland GU, 20 MPa" row did not exist in the guide at
all, whose lowest strength is 25 MPa.

**Those corrections did not take effect for several days, and that is worth
publishing too.** The provider seeded its database only when the factors table
was empty, so once built it never re-read the JSON. The corrected values sat in
version control while the runtime kept serving 142 and kept serving the
fabricated GU 20 MPa record — in a tool whose claim is that every factor is a
sourced record. The database is now a cache keyed on the seed's hash, withdrawn
records are deleted rather than left behind, and six tests cover it. The
catalogue totals were unaffected because no design used the fabricated row, but
the substitution figure was overstated until the fix.

---

## What we throw away, and why

    python scripts/audit_discards.py

Scoring reports what survived, so a discarded thing never appears in one.
Every accuracy bug found in this project was a silent discard — a filter
removing real data while the stage returned a plausible result and raised
nothing — so the discards are instrumented directly.

| Refusal cause | n |
|---|---|
| Name looks like a material | **99** |
| No thickness stated | 46 |
| Other | 20 |
| Implausibly deep | 7 |

**108 of the 172 refusals still carried three or more layers and a stated
depth**, including an 11-layer, 315 mm block on BC_Rowhouse that reads exactly
like a real exterior wall. That looks like a large recoverable loss, and it is
the obvious next improvement to attempt.

It was attempted, and measured, and it is not one. Those blocks score 86.4%
median error against the IFC with none of 25 inside 10%. A name that reads
like a material means the block's edges are in the wrong place, so its
build-up is wrong too. The 63% of refusals that look recoverable are correctly
refused, and we now know that rather than assuming it in either direction.

What this audit does change is where to look next. The remaining causes are
not all equal: "no thickness stated" (46) is a parsing gap where the drawing
does state thicknesses we failed to associate, and that is a different problem
from a mis-split block.

---

## What this does not measure

Stated plainly, because a benchmark that only reports its wins is not a
benchmark:

- **No reference takeoff exists.** CMHC's published Construction Cost
  Estimates contain quantity take-offs but are not in the data package, so
  every figure above is measured against geometry we derived ourselves from
  the IFCs, not against a quantity surveyor's bill.
- **Interior partitions were the hardest quantity here**, and the earlier
  version of this document said they could not be measured at all. That was
  wrong, and the reason is worth keeping: the attempt it reported was the one
  restricting to segments of 1 m or more, which measured −30% on Alberta. That
  minimum was itself deleting the signal — the wall-lineweight group holds 297
  segments under 250 mm, because partition faces break at every door, jamb and
  intersection. Lowering it to 40 mm moved the same approach to a 5.7% median.
  The partitions section above gives the current figures, including the +92%
  outlier and the unresolved `W1`/`P3` depth collision.
- **Cladding and roofing carry no carbon**, because CMHC leaves them
  deliberately unspecified as placeholders. Defaulting them would move about
  12% of a home's embodied carbon on a choice nobody made. They are now
  reported instead as open decisions priced as a range — cladding 1,980–3,774
  and roofing 1,371–2,433 kgCO₂e on AB_Fourplex_01 — which is a decision put in
  front of the builder rather than a number put into the total.
- **A4–A5 are architecture only**, as the scope permits — the extension points
  exist, the modules are not implemented.
- **Ontario's coverage fell 42% to 29%, and that was correct.** This document
  previously said the fall was unexplained and blamed the storey-grouping
  change. Both claims were wrong, and running the old code settled it: at the
  commit before that change, Ontario already read 29%.

  The real cause was a one-layer name filter tightened two commits earlier to
  improve built-depth accuracy. It took Ontario's `R2` roof assembly with it,
  and `R2` is worth exactly the 13% that was lost. The commit that made the
  change reported "ON coverage 9% -> 42%" — a figure measured *before* the
  tightening it contained, never re-measured after. That is the whole failure:
  a threshold tuned on one metric and never checked against another.

  The refusal itself was then challenged with data rather than assumed right.
  Keeping blocks whose name looks like a material but which carry three or
  more layers recovers 77 assemblies across the catalogue — and they are
  wrong: 86.4% median error against the IFC with **none** of 25 inside 10%,
  against 20.1% median and 90 of 223 inside 10% for cleanly-named assemblies.
  Ontario's `R2` reads 124 mm over 5 layers where the model says 490 mm, is
  named "WOOD DECKING", and repeats one glyph-shifted layer twice.

  So the 13 points Ontario lost were 13 points of wrong answer. Coverage and
  correctness are different axes, and this benchmark had been reporting the
  first as though it implied the second.
- **Held-out discipline is imperfect.** These numbers are measured across the
  whole catalogue rather than a strictly untouched slice, so treat them as
  development figures. The honest test is Landmark's own sets, which we have
  never seen.
