# Element build order — what to measure first, and why

The challenge scope, Stage 2, says: *"Build the solution to calculate the biggest
contributors to embodied carbon **using this guide**. Start with the largest
contributors first."* The hyperlinked guide is the **Builders for Climate Action /
City of Nelson "Kootenay Construction Material Impact Guide"** (2026 update, funded
by FortisBC). This file records what it actually says, so our build order is the
organisers' build order and we can cite it.

Downloaded to `reference/kootenay_material_impact_guide.pdf` by
`scripts/fetch_references.py`.

## Contribution by material, for a new low-rise home

All figures the guide attributes to the **2022 Residential Construction Benchmarking
Report**. Percentages are of a new home's *total embodied emissions*.

| Rank | Material category | Share | Guide's functional unit |
|---|---|---|---|
| 1 | **Concrete** | **~35%** | 1 m³ |
| 2 | **Insulation** | **~15%** | 100 m² @ R-5 (continuous) / R-13 (cavity) |
| 3 | **Exterior cladding** | **~12.5%** | 100 m² |
| 4 | **Interior finishes** | **~12%** (6% walls/ceilings, 6% floors) | 100 m² |
| 5 | **Framing & structural** | **~11%** | 100 m² @ 16" o.c. |
| 6 | **Windows** | **~11%** | 100 m² |
| 7 | Roofing | residual, ~3–4% | 100 m² |

That accounts for ~96.5%. The guide also notes embodied emissions are **~50% of a
building's total lifecycle emissions**, and that **A1–A3 is 65–85% of a material's
own lifecycle emissions** — which is why A1–A3 alone is a defensible scope.

## The important consequence for our architecture

The guide is organised by **material**. Our takeoff is organised by **element**. They
map many-to-one, and that is good news:

```
exterior wall area  ->  insulation + cladding + framing + interior finish + sheathing
roof area           ->  roofing + insulation + framing + sheathing
floor area          ->  flooring + framing + subfloor
slab/footing volume ->  concrete + rebar
window area         ->  glazing + frame
```

Ranks 2, 3, 4 and 5 — **50.5% of embodied carbon combined** — are all *layers of the
exterior wall, roof and floor assemblies*. We do not measure them independently. We
measure **assembly areas** accurately and let the layer build-up (from the `A003
ASSEMBLIES SCHEDULE` sheet, cross-checked against the IFC `IfcMaterialLayerSet`)
expand each area into materials.

So the accuracy that matters, in order:

1. **Slab / footing / foundation-wall volume** → concrete, 35% on its own.
2. **Exterior wall area, by assembly tag** → unlocks insulation, cladding, framing,
   sheathing and interior finish together.
3. **Roof and floor area, by assembly tag** → roofing, insulation, flooring, framing.
4. **Window and door area/count, by schedule** → 11%, and high intensity per m².

**This corrects the draft build order in `docs/PLAN.md` Step 10**, which put roof
third. Roofing as a *material* is the smallest of the seven categories; roof **area**
still matters because it carries insulation and framing. Measure roof area early,
but do not spend time on roofing-material precision.

## Carbon values worth knowing (from the guide's charts)

Useful both as sanity bounds and as the basis for Stage 4 swap options. Values are
kgCO₂e per the guide's functional unit, BC/North-American EPDs or BC averages.

**Concrete, per m³** — the single biggest lever:

| Mix | 25 MPa | 30 MPa | 35 MPa |
|---|---|---|---|
| Portland (Type GU) | — | 276 | 315 |
| Portland-Limestone (GUL) + 15% fly ash | 218 | 257 | 291 |
| Portland-Limestone (GUL) + 25% fly ash | 201 | 235 | 270 |
| Portland-Limestone (GUL) + 40% fly ash | **175** | 204 | 233 |

→ A GU→GUL/40%-fly-ash swap at 25–30 MPa is roughly a **26–37% cut in the largest
single category**. This is the headline Stage 4 substitution and it is cited, not invented.

**Windows, per 100 m²** — the highest-intensity category on the chart (axis to 13,000):

| Glazing | Wood | Vinyl | Fibreglass |
|---|---|---|---|
| Double glazed | 7,200 | 8,600 | 11,400 |
| Triple glazed | 8,500 | 9,900 | 12,700 |

Wood-framed units also show a **negative biogenic component (−1,600)**, which the
guide reports separately. We follow suit: biogenic carbon is reported as its own
figure, never netted into the A1–A3 total silently.

**Chart axis maxima**, as a rough intensity ranking per functional unit — windows
(13,000 / 100 m²) ≫ roofing and siding (2,000 / 100 m²) > wall framing and sheathing
(600 / 100 m²) > interior walls and ceilings (500 / 100 m²) > concrete (350 / m³).
Insulation and flooring charts run **negative** (to −1,500 and −2,000) because
bio-based options sequester carbon.

## Element classes we implement, in order

Matching `ElementClass` in `ecarbon/models.py`:

1. `SLAB_ON_GRADE`, `FOOTING`, `FOUNDATION_WALL` — concrete + rebar
2. `EXTERIOR_WALL` — insulation, cladding, sheathing, framing, interior finish
3. `ROOF_ASSEMBLY` — roofing, insulation, framing, sheathing
4. `FLOOR_ASSEMBLY` — flooring, framing, subfloor
5. `WINDOW`, `DOOR` — from the openings schedule
6. `PARTY_WALL`, `INTERIOR_PARTITION` — interior finishes, framing
7. `STAIR`, `CLADDING`, `INSULATION`, `OTHER` — only if time allows

The scope is explicit that *"it may not be realistic to include every building element
in the prototype during the sprint"* — so stopping after 5 is a legitimate outcome,
provided the gap report says which classes were not covered.

## Caveats to state in the submission

- The benchmarking percentages are **Canadian low-rise averages**, not Alberta-specific
  and not per-design. They set our *build order*; they are never used as carbon factors.
- The guide's own factors are **Kootenay/BC-weighted**. Landmark builds in Alberta, so
  the factor store records geography per row and we prefer AB/Prairie or
  national-average records where available. See `RESEARCH.md` §9.
- The guide reports A1–A3, matching our scope boundary exactly.
