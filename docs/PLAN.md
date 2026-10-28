# Embodied Carbon Challenge — Research Findings & Build Plan

> **Status:** Phase A (research) complete. Phase B (plan) pending answers to the open questions at the end.
> **Step 1 of execution will be to copy the research half of this file to `RESEARCH.md` in the repo** (plan mode permits editing only this file).

---

# PART 1 — RESEARCH FINDINGS

## 0. What I actually inspected

Everything below is from direct inspection, not assumption. Because `poppler`/`PyMuPDF` are **not installed** on this machine (system Python is 3.9.6 with zero third-party packages, see §9), I wrote a dependency-free PDF reader (xref streams + object streams + content-stream op census + per-font `ToUnicode` CID decoding) in `/tmp/ecx/pdfmin.py` and `/tmp/ecx/pdftext.py` and used it on all 53 drawings PDFs, 73 Building Performance Reports, the List-of-Drawings PDFs, the CMHC User Guide, and both challenge PDFs. IFC and HOT2000 were parsed with stdlib regex/XML. **That throwaway parser should be rewritten properly as Step 2** — but it means every number here is measured.

---

## 1. The scope PDF vs your brief — differences that matter

Source: `Embodied Carbon Assignment Details/BWT_EmbodiedCarbon_Challenge_Scope-Draft-V2-August-19-2026.docx-1 2.pdf` (4 pages) and `Embodied Carbon Challenge - Data Package.pdf` (2 pages). Your brief is a faithful paraphrase of the scope. Five real differences:

| # | Finding | Impact |
|---|---|---|
| 1 | **Two links in the scope PDF are missing from your brief.** The scope's Stage 2 says "calculate the biggest contributors to embodied carbon **using this guide**" — the hyperlink points to the **Builders for Climate Action "Kootenay Construction – Material Impact Guide"** (`buildersforclimateaction.org/uploads/1/5/9/3/15931000/kootenay_construction_-_material_impact_guide.pdf`). The second is **IStructE "A brief guide to calculating embodied carbon"**. | **High.** The organisers have *prescribed* an element-prioritisation guide. Our "build in order of carbon contribution" ordering should match it, and we should cite it. I could not read it (10 MB, exceeds WebFetch limit) — **manual download required, Step 0.** |
| 2 | Scope Stage 2: "across the element list **attached in the data package**". Scope "Primary Reference Data": "**template whole-building LCA shown in data package**". **Neither is in our Data Package PDF** — it is 2 pages of links only. | **High.** The sponsor's element/material list is the exact thing criterion 2 scores "element list coverage" against, and we do not have it. **Ask the organisers.** Until then, use the Kootenay guide + CMHC assembly schedules as a proxy element list. |
| 3 | Scope says traditional assessments "can take **weeks** and cost thousands of dollars". Your brief says "**5–6 months**" and "~2 month design cycles". | Minor but pitch-relevant. Those numbers are **not** in the scope. Use the scope's own framing, or source the months claim separately before putting it on a slide. |
| 4 | Rubric criteria are numbered 1,2,3,4,5,6,7,**9** — "The X factor" is #9 in the source (doc typo). Weights total exactly 100%. Your weights are all correct. | None, cosmetic. |
| 5 | Data Package says "Teams develop against the public catalogues in **Part 3**" — it means Part 2. Part 3 is sponsor data, finalists only. | None, confirms the split. |

Confirmed exactly as you stated: vector PDF is the **only** supported format; A1–A3 only; module scope must stay visible; only like-for-like modules summed; A4–A5 extensibility required; scoring at **both** Semi-Finals and Demo Day; final scoring on unseen Landmark sets.

---

## 2. Per-design inventory (all 52 packages / 53 drawing sets)

`pg` = pages, `paths` = vector path ops (thousands), `text` = text-show ops, `lyr` = PDF layer (OCG) names, `W/S/Wi` = IFC walls/slabs/windows, `EC` = published total kgCO₂e, `I` = kgCO₂e/m².

| Design | Reg | pg | paths k | text | lyr | IFC W/S/Wi | h2k | EC | I |
|---|---|---|---|---|---|---|---|---|---|
| AB_ADU_01 | AB | 39 | 562 | 9235 | 16 | 39/7/8 | 1 | 46,017 | 525 |
| AB_ADU_02 | AB | 41 | 588 | 9657 | 16 | 34/10/12 | 1 | 57,150 | 480 |
| AB_Fourplex_01 | AB | 46 | 738 | 11347 | 1 | 92/11/42 | 1 | 162,043 | 530 |
| AB_Fourplex_02 | AB | 51 | 951 | 13891 | 1 | 153/14/45 | 1 | — | — |
| AB_Rowhouse_01 | AB | 41 | 648 | 10773 | 1 | 157/14/42 | 1 | — | — |
| AB_Rowhouse_02 | AB | 47 | 789 | 12316 | 1 | 151/22/35 | 1 | — | — |
| AB_Sixplex | AB | 51 | 983 | 14056 | 1 | 158/14/50 | 1 | — | — |
| ATL_ADU_01 | ATL | 23 | 341 | 5252 | 154 | 17/2/7 | 1 | — | — |
| ATL_ADU_02 | ATL | 24 | 351 | 5304 | 188 | 34/6/9 | 1 | — | — |
| ATL_Fourplex_01 Opt1 | ATL | 34 | 739 | 9396 | 273 | 126/8/32 | 1 | — | — |
| ATL_Fourplex_01 Opt2 | ATL | 34 | 713 | 10084 | **0** | 129/10/33 | — | — | — |
| ATL_Fourplex_02 | ATL | 35 | 815 | 13537 | 223 | 151/14/37 | 1 | — | — |
| ATL_Fourplex_03 | ATL | 33 | 634 | 9490 | 155 | 138/13/27 | 1 | — | — |
| ATL_Sixplex | ATL | 37 | 871 | 14639 | 227 | 185/10/31 | 1 | — | — |
| ATL_Stacked_TH_01 | ATL | 35 | 671 | 8719 | 215 | 168/36/43 | 1 | — | — |
| ATL_Stacked_TH_02 | ATL | 32 | 649 | 10829 | 217 | 248/21/58 | 1 | — | — |
| BC_ADU_01 | BC | 28 | 476 | 5811 | 107 | 22/4/4 | **0** | 17,436 | 349 |
| BC_ADU_02 | BC | 29 | 498 | 6122 | 144 | 32/5/10 | **0** | 21,671 | 231 |
| BC_Duplex | BC | 35 | 638 | 8028 | 172 | 114/14/28 | **0** | 51,298 | 189 |
| BC_Fourplex_01 | BC | 36 | 980 | 8395 | 178 | 122/17/30 | **0** | 57,860 | 155 |
| BC_Fourplex_02 | BC | 40 | 777 | 8894 | 165 | 169/23/48 | **0** | 78,517 | 141 |
| BC_Rowhouse | BC | 35 | 627 | 8403 | 142 | 77/9/24 | **0** | 44,984 | 178 |
| BC_Sixplex Courtyard | BC | 49 | 919 | 10787 | 233 | 173/21/50 | **0** | 92,237 | 160 |
| NOR_ADU_Mun_Garage | NOR | 35 | 502 | 9900 | 20 | 45/6/4 | 1 | — | — |
| **NOR_ADU Municipal** | NOR | 31 | **2754** | **25** | 1 | 26/33/5 | 1 | 28,865 | 544 |
| **NOR_ADU Tanked** | NOR | 33 | **2839** | **528** | 1 | 21/54/5 | 1 | 27,018 | 540 |
| **NOR_Fourplex Mun** | NOR | 37 | **3853** | **461** | 1 | 280/44/18 | 1 | 247,847 | 605 |
| **NOR_Fourplex Tanked** | NOR | 37 | **4084** | **17** | 1 | 127/**808**/31 | 1 | 199,417 | 433 |
| **NOR_Rowhouse Mun** | NOR | 37 | **3854** | **16** | 1 | 230/33/32 | 1 | 173,942 | 481 |
| **NOR_Rowhouse Tanked** | NOR | 36 | **3636** | **8** | 1 | 68/**812**/21 | 1 | 98,963 | 458 |
| **NOR_Sixplex Mun** | NOR | 43 | **4636** | **34** | 1 | 384/62/23 | 1 | 276,076 | 451 |
| **NOR_Sixplex Tanked** | NOR | 42 | **4731** | **64** | 1 | 233/**650**/28 | 1 | 223,906 | 303 |
| ON_ADU_01 | ON | 37 | 745 | 11338 | 1 | 29/1/7 | 1 | 23,986 | 410 |
| ON_ADU_02 | ON | 25 | 753 | 8025 | 1 | 34/4/11 | 1 | 31,664 | 333 |
| ON_Fourplex_01 | ON | 33 | 1328 | 10869 | **0** | 123/8/23 | 1 | 187,539 | 518 |
| ON_Fourplex_02 | ON | 32 | 1139 | 9984 | **0** | 125/6/21 | 1 | 130,059 | 429 |
| ON_Sixplex | ON | 35 | 1022 | 10213 | **0** | 143/10/24 | 1 | 224,488 | 499 |
| ON_Stacked_TH_01 | ON | 35 | 1233 | 9157 | **0** | 211/20/36 | 1 | 88,952 | 443 |
| ON_Stacked_TH_02 | ON | 36 | 1297 | 9823 | 13 | 239/22/42 | 1 | 103,850 | 438 |
| QC_ADU_01 | QC | 26 | 390 | 8416 | 1 | 25/2/4 | 1 | 33,628 | 731 |
| QC_ADU_02 | QC | 28 | 558 | 8360 | 1 | 40/6/6 | 1 | 70,202 | 615 |
| QC_Fourplex_01 | QC | 34 | 796 | 11208 | 1 | 126/9/24 | 1 | 261,490 | 714 |
| QC_Fourplex_02 | QC | 34 | 818 | 11620 | 1 | 154/14/22 | 1 | 181,241 | 441 |
| QC_Rowhouse_01 | QC | 31 | 620 | 9475 | 1 | 104/7/16 | 1 | 160,350 | 439 |
| QC_Rowhouse_02 | QC | 33 | 690 | 11118 | 1 | 122/8/25 | 1 | 253,191 | 661 |
| QC_Sixplex | QC | 37 | 1040 | 13349 | 1 | 194/24/36 | 1 | 348,367 | 506 |
| SKMB_ADU_01 | SKMB | 23 | **117** | 5029 | 64 | **0/0/0** | 2 | 32,601 | 563/593 |
| SKMB_ADU_02 | SKMB | 24 | **126** | 5340 | 68 | **0/0/0** | 2 | 49,068 | 430/467 |
| SKMB_Fourplex_01 | SKMB | 30 | 693 | 11611 | 1 | **0/0/0** | 2 | 178,124 | 573 |
| SKMB_Fourplex_02 | SKMB | 30 | 722 | 12491 | 1 | **0/0/0** | 2 | 159,115 | 394 |
| SKMB_Sixplex | SKMB | 32 | 969 | 13066 | 1 | **0/0/0** | 2 | 251,588 | 472 |
| SKMB_Triplex | SKMB | 29 | 674 | **79469** | 1 | **0/0/0** | 2 | 107,659 | 512/555 |
| SKMB_Rowhouse | SKMB | 34 | 863 | 11641 | 2 | **0/0/0** | 2 | 101,215 | 422/452 |

Sheet sizes are uniformly **36×24 in or 24×36 in**. Page counts 23–51.

### Corrections to your notes
- **`atl_fourplex_03...zip` is already extracted** — no zip files remain anywhere. It is the one package **missing its `List of Drawings` PDF**.
- **SKMB packages have 2 HOT2000 files and 2 Building Performance Reports each** (separate MB and SK variants), not 1.
- **"Residential Energy Calculations" exists only for AB_ADU_01 and AB_ADU_02** (PDF + xlsx) — not catalogue-wide.
- **Every package has an `*_Energy and Carbon` folder** — not in your notes, and it is the single most valuable folder in the download (§6).
- BC-has-no-HOT2000 and ATL_Fourplex_01-has-two-options: both confirmed.
- File census: 1653 DWG, 298 PDF, 53 IFC, 52 h2k, 24 xlsm, 2 xlsx, 57 ctb. 2150 files, 2.7 GB.

---

## 3. Vector vs raster — the single most important extraction finding

**All 53 drawing sets are genuinely vector** (hundreds of thousands to millions of path ops; no page is a scan). But text availability splits them hard:

- **44 sets: vector geometry + 5,000–14,600 extractable text ops.** Fully parseable.
- **8 NOR sets (all except NOR_ADU_Municipal_Garage): vector geometry but 8–528 text ops across 31–43 pages — effectively zero.** Produced by *Acrobat Distiller 25.0*; all text has been **converted to vector outlines**, which is why their path counts are 2.7 M–4.7 M (4–7× everything else). They also carry 38,000–80,000 image XObject draws (rasterised hatch tiles).

**Consequence:** for 8 of 52 designs there are **no readable dimension strings, no readable schedules, no readable sheet titles**. Your cross-validation plan (§strategy 3) loses its "parsed dimension strings" and "schedules" sources on those designs. This is not a defect to fix — it is **exactly the generalisation case the rubric rewards**: criterion 1 explicitly scores "reports what it cannot read rather than assuming". Landmark's sets could be either kind.

→ **Design decision:** the gap report must detect "vector-but-textless" at intake and say so, and an OCR fallback (render page → OCR) is a genuine requirement, not a nice-to-have. Recommend treating the 8 NOR sets as a dedicated **"hard mode" held-out slice**.

---

## 4. Four free signals in the PDFs that most teams will miss

These are the differentiators. All verified by inspection.

**(a) Revit sheet metadata on the page object.** Revit-exported pages carry custom keys:
```
/revit_metadata_view_sheet_number (A010)
/revit_metadata_view_name (A010 - SITE PLAN & CODE MATRIX)
/revit_metadata_view_type (VT_Drafting)
```
→ **Stage 1 sheet classification is free on these pages**, with no vision model. Present on AB_ADU_01/02 (13 pages), AB_Rowhouse_02 (18), AB_Fourplex_01 (18), ON_ADU_01 (22), NOR_ADU_Mun_Garage (3).

**(b) The drawings PDF is a concatenation of several firms' exports.** In AB_Fourplex_01, pages 1–18 carry Revit metadata (architectural); pages 19–46 carry none — those are the Structural/Mechanical/Electrical sheets, exported by AutoCAD and appended. **Drawing conventions change *within* a single PDF.** Any per-file assumption about toolchain is wrong; detection must be per-page.

**(c) AIA-standard CAD layer names (PDF optional content groups).** Present and rich on ~20 sets: `A-WALL`, `S-FNDN`, `S-FTG`, `A-FLOR`, `A-ANNO-DIMS-25`, `G-ANNO-TTLB`, `A_EF-Opening-Window`, `M-HVAC-DUCT-SUPP`. ATL/BC sets carry 107–273 layer names; ATL layer names even embed the firm's job number (`14-24-082`, `24188 - CMHC title block`). But ~half the sets have **only `Watermark`** (layers flattened on export) and 4 have **zero** OCGs.
→ **Do not build on layers.** Instead: **use the ~20 layer-labelled sets to auto-generate ground-truth labels for the geometry-only classifier** that must work on the rest. That is a free, large, high-quality training/validation set for element classification, and it is the strongest technical idea in this research.

**(d) Embedded world-to-page transforms.** Marked-content property dicts carry `<</PRECISION 5 /UNITS(mm) /VP[...4×4 matrix...]>>` — multiple per sheet, one per viewport at its own scale. Counted 2–223 per file; present on 23 sets, absent on 30.
→ Potentially solves scale *exactly* rather than by OCR-ing "SCALE: 1/4" = 1'-0"" or measuring a scale bar. **Caveat: I could not derive the unit convention confidently** (values 0.7207 / 1.4414 / 72.07 on one sheet don't map cleanly to 1:48). **Must be empirically calibrated against a known IFC dimension before trusting it** — that's a concrete early task.

**(e) Dual-unit dimensions.** On AB_Fourplex_01 main floor plan: 84 metric strings (`7000`) and 85 imperial strings (`23' - 0"`) for the same dimensions. Sections carry storey datums (`T/O F/F SECOND  3.000 m / 9'-10 1/8"`).
→ **Two independent representations of every dimension on the same sheet** = a built-in agreement check that directly feeds your measured/inferred/assumed labelling.

**(f) Assembly tags cross-reference cleanly.** Section sheet A300 carries tags `W2, P2, P3, F1, F2, R2`; these are exactly the keys on sheet **A003 ASSEMBLIES SCHEDULE** — and exactly the names inside the IFC (§5). Chain: *section tag → assemblies schedule → layer build-up → materials → carbon factor*, verifiable end-to-end.

---

## 5. IFC ground truth — weaker than your brief assumes, but still the right benchmark

All 53 are **IFC2X3**. 46 are Autodesk Revit exports; 7 (all SKMB) are **Vectorworks Architect 2024**.

**What the IFC does NOT give you — correction to the brief:**
- **52 of 53 IFCs contain zero `IfcElementQuantity` / `IfcQuantityVolume` / `IfcQuantityArea`.** Only `ATL_Fourplex_03` has them (351 / 336). **There are no pre-computed quantities.** Quantities must be derived from geometry — so the benchmark harness needs its own IFC quantity engine (walls are `IfcExtrudedAreaSolid` + `IfcRectangleProfileDef`, 409 and 344 in AB_Fourplex_01; complex elements are `IfcFacetedBrep`). That is real work and must be scheduled, not assumed.
- No cost data, no carbon data, no waste factors, no fastener/accessory quantities.

**What it gives you, and it's good:**
- Wall type names carry the drawing's assembly tag verbatim: `IFCWALLSTANDARDCASE(...,'Basic Wall:W2 -RATED EXTERIOR ENVELOPE WALL:6595017',...)`, `'Basic Wall:P2 - 2x6 Stud'`, `'Basic Wall:N1 - Foundation'`.
- `IfcMaterialLayerSet` with per-layer thickness in mm: `IFCMATERIALLAYERSET((#1501..#1505),'Basic Roof:R2 - Exterior Envelope Roof')`, `IFCMATERIALLAYER(#1472, 16., $)`.
- **Materials use a standardised `CMHC_` prefix** — `CMHC_Metal Roof`, `CMHC_Wood Framing`, `CMHC_Plywood`. 16–77 materials per design. **One material→factor mapping table covers the whole catalogue.** Big win for Stage 3.
- `Pset_QuantityTakeOff` property set exists (contents not yet examined — worth 20 minutes).

**IFC quality rating:**
- **Good (39):** AB, ATL, BC, ON, QC — semantic walls/slabs/footings/windows/doors + material layer sets.
- **Questionable (6):** NOR `_Tanked` variants — 650–812 `IfcSlab` and **zero `IfcFooting`**, versus 44–62 slabs / 14–24 footings for the matching `_Municipal`. The Municipal/Tanked pairs are **modelled differently, not parameterised variants** — so they are *not* the clean "variant-as-delta" test case your brief hoped for. Use ATL_Fourplex_01 Opt1/Opt2 and AB_ADU_01/02 for that instead.
- **Unusable (7):** all SKMB — **zero** `IfcWall`/`IfcSlab`/`IfcWindow`/`IfcDoor`/`IfcFooting`. Vectorworks exported pure B-rep (`IfcOpenShell`/`IfcFace`/`IfcPolyLoop`) with no semantic element types, though it *does* carry 723 `IfcMaterial` and 354 `IfcMaterialLayerSet`. **Exclude all 7 SKMB designs from element-level accuracy scoring** (they remain useful for PDF-extraction robustness testing).

That is **39 designs with usable element-level ground truth**, not 52 — which materially changes your proposed 25–30 / 10–12 / 10–12 split.

---

## 6. The `Energy and Carbon` folder is the hidden prize

**Building Performance Reports (73 files) contain published whole-life carbon results.** I parsed **71 of 73** successfully. Each gives: location + climate zone, gross and conditioned floor area, storeys/units, total EC (kgCO₂e), **EC/GFA (kgCO₂e/m²)**, biogenic carbon, and A1–A5 / B4–B5 / C2–C4 splits, plus nominal assembly RSI/R values (roof, wall, floor, door, window U).

Example — `AB_Fourplex_01`: Edmonton AB, CZ 7A, GFA 306 m², conditioned 303 m², 2-storey 4-unit; **total EC 162,043 kgCO₂e; EC/GFA 530**; biogenic 46,695; A1–A5 107 tCO₂e, B4–B5 42, C2–C4 12.

Across the catalogue, intensity ranges **141 → 731 kgCO₂e/m²** (ADUs high, large multiplexes low). That 5× spread is itself a finding: "is our number plausible?" has a wide answer.

**Critical scope caveat:** these totals are **A1–A5 + B4–B5 + C2–C4**, *not* A1–A3. Under the challenge's own rule — "only like-for-like modules may be summed" — **our A1–A3 figure is not directly comparable to the published total.** Use it as (a) an upper bound, (b) an intensity sanity band, and (c) a *demo asset*: showing the published CMHC number, our A1–A3 number, and an explicit module reconciliation is precisely the discipline criterion 3 rewards.

**HOT2000 `.h2k` files are plain XML** (`<HouseFile>`, HOT2000 v11.13), trivially parsed with stdlib `xml.etree`. They contain per-surface `<Measurements length="16.1849" area="118.0333">` for walls and ceilings, `<Slab exposedSurfacePerimeter="56.0832">`, 17 `<Window>` with frame geometry/SHGC, 26 `<Door rValue>`, 32 `<Construction>` blocks, basement/crawlspace sections.
→ **A genuine second independent ground truth for exterior wall area, ceiling/roof area, window area and slab perimeter.** Caveat: these are *thermal envelope* areas (gross, by orientation) — no interior partitions, no structural quantities. Still covers two of the biggest quantities.
→ **Business insight:** every Canadian builder doing energy-code compliance already has an `.h2k`. Ingesting it is a cheap, credible accuracy boost and a strong "we fit your existing workflow" story.

**BC Step Code checklists (24 `.xlsm`)**: 3 per BC design (CZ4/5/6), 6 for BC_Sixplex. BC's three reports per design carry **identical EC values** (only operational differs) — confirming EC is climate-independent, so BC contributes 7 unique EC data points, not 21.

**CMHC published more than we have.** The User Guide (§7, §10) states that for every design CMHC produced **sample LCAs** ("assumptions were made to complete the sample LCAs for each design", using "average embodied carbon values across material families") and **Construction Cost Estimates** in which "**detailed unit costs and quantity take-offs have been incorporated**" at CIQS **Class B, ±15%**, plus a **Materials Guide** and **Climate Resilience Guide** — all "provided on the catalogue website". **None of these are in our 2.7 GB download.** The Data Package PDF also claims packages include cost estimates; ours don't.
→ **Highest-value outstanding action: download the Construction Cost Estimates from housingcatalogue.cmhc-schl.gc.ca.** A published quantity take-off per design is *the* reference takeoff for criterion 2 (30% of the score) and we currently have no takeoff ground truth at all except what we derive ourselves from IFC. I could not enumerate the site's downloads (JS-rendered); needs a browser.

---

## 7. DWG and licensing

**DWG (1653 files):** signatures are `AC1032` (AutoCAD 2018, ~96% of sample) and `AC1024` (AutoCAD 2010). LibreDWG's support for AC1032 is poor; ODA File Converter handles it but is a manual GUI/EULA-gated download. **Verdict: not worth it.** The PDFs are already fully vector and the IFCs already carry semantics and material layers; DWG adds a conversion dependency, a licence question, and no information we can't already get. Revisit only if PDF geometry classification stalls badly.

**CMHC licence — this one is a hard constraint.** From the User Guide Appendix (the standalone Terms PDF has no extractable text; the Appendix is the same document):
- CMHC grants a **revocable, royalty-free, non-exclusive limited licence** to use/copy/modify/adapt the Designs **solely to create Derived Designs for planning, design and/or construction of a new structure at a site-specific location in Canada** ("the Purposes").
- "You are **expressly restricted and prohibited from distributing, licensing, selling, or otherwise making available any Designs**" outside those Purposes without prior written CMHC consent.
- Derived Designs must carry a specific attribution/disclaimer notice; you may not obscure seals, notices or version numbers.
- CMHC may require use be "limited or discontinued" at any time.

**Conclusions:**
1. **Never commit the `CMHC Plans/` tree to git** — pushing to GitHub is distribution. This applies to a private repo too, and absolutely to a public one.
2. Using the files as **internal development and test data** is a grey area, not a granted Purpose. Low practical risk for a hackathon, but **do not redistribute, do not ship them inside a product, and do not publish derived drawings.**
3. **Publishing aggregate accuracy statistics** ("median wall-area error 6% across 39 designs") is fine and is not distribution — that protects the published-benchmark differentiator.
4. Any screenshot in the pitch deck showing a CMHC sheet should carry the attribution line.

**Repo state:** `EmbodiedCarbon/` is a fresh clone, **zero commits, no `.gitignore`**, and `git status` currently lists `CMHC Plans/` and `Embodied Carbon Assignment Details/` as untracked. **One `git add .` commits 2.7 GB and breaches the licence.** This is the single most urgent action in the whole plan.

**Recommended data strategy:** `.gitignore` the data; keep `CMHC Plans/` outside the repo entirely (e.g. `~/ec-data/`) referenced by an env var; commit a `scripts/fetch_data.py` that re-downloads from CMHC per design; commit only small derived artefacts (per-design JSON manifests, extracted ground-truth quantities, benchmark results). **Not Git LFS** — it still stores and distributes the files. Teammate runs the fetch script once.

---

## 8. Prior art and the LLM evidence

**Handoff-H1** (`handoff.ai/tech/h1-model-release`) — loaded; no account needed. This is the serious competitor and the most useful number in the whole research:

| System | Composite | Coverage | Precision@25% |
|---|---|---|---|
| **Handoff-H1** | **81.6%** | 86.1% | 78.8% |
| Professional human estimators | 77.6% | 65.5% | **87.9%** |
| Seven frontier AI models | 34.7–61.4% | — | — |

On *TAKEOFFBENCH-V1*: 10 residential blueprint sets, 1,348 primary-tier items, 9 trades, raw PDF in. Architecture: **perception layer** (purpose-built CV extracting typed primitives — rooms, walls, doors, dimensions, scales) → **knowledge layer** (curated construction knowledge base) → **orchestration layer** (vision agents + task-specific tools). Admitted weaknesses: precision lags coverage ("more than one matched quantity in five still falls outside the 25% band"); **continuous measurements (linear/area) are harder than discrete counts**; **siding is "the system's clearest open problem"**; residential-only; knowledge base needs constant maintenance. API available on a paid tier.

**Calibrate expectations against this.** A funded, purpose-built team reports ~79% of quantities within **±25%**, and human estimators only reach 87.9% precision — **the reference takeoff itself has spread**. Any internal target of "within 5%" is unrealistic; **±10% on the top-5 carbon drivers with honest confidence labels is a winning result.** Our differentiation vs Handoff: they do multi-trade cost takeoff with no carbon layer and no traceability/uncertainty story; we do carbon-first with click-to-trace, module-scope discipline, a gap report, and a published benchmark.

**arXiv 2508.16081 — your brief's identification is wrong.** It is **"CEQuest: Benchmarking Large Language Models for Construction Estimation"** (Wu, Wang, Liu; FIU/UF; 22 Aug 2025; 5 pages; code at `github.com/mlsysx/CEQuest`), **not** "stress testing LLMs for construction drawing interpretation."

More importantly, **it is much weaker evidence than the brief assumes.** CEQuest is **164 text questions** — 101 multiple-choice (avg 3.59 options) and 63 true/false — written by domain experts from estimating textbooks. **The models were never shown a drawing.** Results (mean±std over 5 runs):

| Model | Size | Accuracy |
|---|---|---|
| Gemma 3:4b | 3.3 GB | 61.83 ± 0.30 |
| Phi-4:14b | 9.1 GB | 64.02 ± 0.55 |
| LLaVA:34b | 20 GB | 62.56 ± 1.06 |
| Llama 3.3:70b | 43 GB | 65.37 ± 0.60 |
| **GPT-4.1** | — | **75.37 ± 1.13** |

Subject areas: general construction knowledge; drawing element identification; drawing organisation/view types; spatial reasoning & cross-referencing; quantity takeoff & estimating.

Documented failure modes, all three directly useful:
1. **Format non-compliance** — models emit prose and omit the actual choice (Llama 3.3 frequently), so outputs aren't machine-parseable. → **Force structured output with schema validation and retry; never free-text parse.**
2. **Plausible-but-wrong reasoning** — Phi-4 confidently asserted an elevation "does not show internal elements below ground level, like the depth of footings." → **Never let a model's explanation stand as evidence; require a geometric or textual citation.**
3. **Missing domain conventions** — a slab at 5.33 cy: Phi-4, LLaVA and GPT-4.1 all chose "5 cy" (nearest integer) when estimating practice **rounds up** for waste. → **Encode construction conventions (waste factors, rounding, stud spacing, nominal-vs-actual) as explicit rules, not as something the model is trusted to know.**

So: **the paper does not show LLMs failing to read drawings — it shows they lack construction domain knowledge even in pure text.** That still supports "LLM proposes, geometry verifies", but for a different reason than stated, and it is the honest version to put in a pitch. The paper also cites **FloorPlanCAD** (ICCV 2021, large-scale CAD panoptic symbol-spotting dataset) — a genuinely useful reference for symbol/element detection.

---

## 9. Carbon data sources — what each can realistically give us

| Source | Loaded | Account / key | Licence for our product | Verdict |
|---|---|---|---|---|
| **BEAM** (Builders for Climate Action) | ✅ | Pay-what-you-can, no paywall | EULA not read | **Best methodology fit.** Explicitly **A1–A3 cradle-to-gate**, explicitly **low- and mid-rise residential**, Canadian, covers exactly our scope — structure, enclosure, partitions (foundations, walls, floors, roofs, windows, cladding) and *excludes* MEP and finishes. Delivered as a **Google Sheet**, so programmatic use means extracting factors — **check the EULA before copying values into our DB.** |
| **EC3** | ✅ | **Yes** — EC3 account, and a **Professional account with a business email** for API (generic domains blocked) | Free tier: **45 tokens/min, 400/hr, 2,000/day, 10,000/month**; "commercial production applications" need paid access; **attribution to Building Transparency required** | 50,000+ valid EPDs, North America. **Cannot be the live backend for a demo at scale.** Use it to source a cached, attributed snapshot for the materials we actually need, behind a pluggable provider interface. |
| **ICE Database** (Univ. of Bath) | ✅ | Free form download, v5.0 (Jun 2026) | ⚠️ **"ICE Database Educational must not be used for commercial applications, including project calculations, carbon assessments, tools, software, reporting, or any internal business or consultancy activity."** Commercial = separate paid **IC+** licence | **Do not use.** The Data Package lists it as a free open source; that is misleading for our purpose. 200+ materials, 30+ categories. **Flagging this is itself a credibility win with judges.** |
| **Athena Impact Estimator** | ✅ | Free; **Windows desktop** (Mac via their remote server, free) | Not stated | 1,200+ North American assembly combinations, regionalised LCI (grids, transport, manufacturing). **No API or machine-readable export found.** Useful as an independent cross-check on a couple of designs, not as a backend. |
| **NRC National Guidelines for wbLCA** | ✅ | Free | Government publication | 2022 (rev. 17 Aug 2022), 136 pp, DOI 10.4224/40002740. Direct PDF: `nrc-publications.canada.ca/eng/view/ft/?id=f7bd265d-cc3d-4848-a666-8eeb1fbde910`. **Not yet read** — this is the methodology the judges' "defensible" standard points at. **Read in Step 0.** |
| **Carbon Leadership Forum tool list** | ✅ | Free | — | Confirms the landscape. Notable additions: **BHoM** (open-source, multi-database: EC3 + Quartz + ICE), **Beacon** (free Revit plugin, A1–A3, North American EPDs), OneClick LCA Planetary, ZGF Concrete Tool (NRMCA data). BHoM is worth 30 minutes as a reference implementation of a multi-provider factor layer. |
| **EC3 primer for AEC professionals** | ✅ (read locally) | Free | — | Confirms the uncertainty framing we should adopt: EPD GWP values carry **statistical uncertainty shown as range/whisker bars**, and the point of EC3 is "assessing the uncertainty within the different EPDs available, including industry-average EPDs". Directly supports our uncertainty-range differentiator. |
| **IStructE brief guide** | ✅ (read locally) | Free | — | Gives the canonical formula set. `EC = Σ(quantity × ECF)`; **`A5w = WF × (A1–A3 + A4 + C2 + C3–C4)`** where WF is the waste factor; density conversions (concrete 2400 kg/m³, rebar 90 kg/m³); and **A1–A3 ≈ 50% of total A1–C4**. This is the schema for A4–A5 extensibility the scope demands. |
| **Autodesk sustainability API** | ❌ | — | — | Docs page is JS-rendered; returned only nav chrome. **Needs a browser.** |
| **Kootenay Material Impact Guide** | ❌ | Free | — | **10 MB, exceeds WebFetch limit. Must download manually — and it's the guide the scope prescribes.** |
| **enbix BEAM training** | ✅ | $15, **Oct 15–16, already passed**, tickets closed | — | No recording mentioned. Dead end. |
| **CMHC catalogue site** | ⚠️ partial | Free | §7 | Homepage doesn't enumerate downloads (JS-rendered). **Needs a browser** to get the Construction Cost Estimates / sample LCAs / Materials Guide (§6). |

---

## 10. Feasibility — verified, with one blocker

- **Blocker: the machine cannot run the stack as-is.** System Python is **3.9.6** (`/usr/bin/python3`) with **no third-party packages** and an old pip (no `--dry-run`). Current PyPI releases require newer Python: **PyMuPDF 2.0 → ≥3.11**, **IfcOpenShell 0.9.0 → ≥3.10, <3.16**, **Shapely 2.2 → ≥3.11**, **DuckDB 2.0 → ≥3.11**. macOS arm64 wheels exist for all of them on cp311–cp313. **Step 0 must install Python 3.12/3.13 (Homebrew is present at `/opt/homebrew/bin/brew`; `uv` is not installed) and create a venv.** Node v25.9.0 is available if we want a JS frontend.
- **No PDF/CAD CLI tools at all**: `pdftotext`, `pdfinfo`, `mutool`, `qpdf`, `gs`, ODA File Converter, ImageMagick all absent. `brew install poppler mupdf-tools` needed — note Claude Code's own `Read` tool cannot open PDFs until poppler is installed.
- **IfcOpenShell: available and the right choice** (wheels for cp310–cp315 on mac arm64). Not yet run.
- **PyMuPDF: available**, and everything I proved by hand with ~200 lines of stdlib it does properly — paths with transforms, text with positions, OCGs, annotations, page rendering for OCR.
- **Verified feasible by direct demonstration, not assumption:** vector path extraction, positioned text extraction with CID/ToUnicode decoding, OCG layer-name extraction, Revit page-metadata extraction, viewport `/VP` matrix extraction, IFC entity/material-layer parsing, HOT2000 XML parsing, and bulk BPR numeric extraction (71/73).
- **Not verified:** the `/VP` unit convention (§4d); `Pset_QuantityTakeOff` contents; whether IFC-derived quantities actually agree with PDF-derived ones (that is the first real experiment); EC3 API endpoint shapes (behind login); BEAM and Athena licence text.

---

## 11. Where I think your strategy needs to change

Mostly it holds up well. Six adjustments, each with a reason:

1. **The dev/validation/held-out split must be 39 designs, not 52.** The 7 SKMB designs have no usable IFC semantics (§5) and must be excluded from element-level accuracy scoring; the 6 NOR `_Tanked` IFCs are internally inconsistent (800 slabs, zero footings). Suggested: **dev 20, validation 9, held-out 10** from the 39, with SKMB (7) + NOR-textless (8) kept as a separate **robustness suite** scored on "did we correctly report what we cannot read", not on quantity error.
2. **Split by export toolchain, not by firm or region.** The real convention boundary is the toolchain, and §4b shows **it changes within a single PDF** (Revit arch pages + AutoCAD structural pages in one file). Grouping by region leaks, because one region's sets share an exporter. Group by detected toolchain signature (Revit-metadata / AIA-layered AutoCAD / flattened / Distiller-outlined / Vectorworks) and hold out whole groups.
3. **Keep Alberta central — but AB is not the easy case.** AB_ADU_01/02 have Revit metadata *and* 16 layer names; AB_Fourplex/Rowhouse/Sixplex have `Watermark` only and no Revit metadata on most pages. So Alberta alone spans two toolchains. Good — it means Alberta-first does not over-fit. Keep assembly and factor defaults Alberta-first as you proposed (NBC(AE), Edmonton CZ 7A, confirmed by the BPRs).
4. **"Cross-validate from 2+ independent sources" needs a documented fallback ladder,** because the sources are not uniformly available: dimension text (44/52), layers (~20/52), `/VP` scale (23/52), Revit metadata (5 sets, partial), HOT2000 (45/52), schedules (needs text). Define the ladder explicitly and let the confidence label fall out of *which* rungs agreed. That is what makes measured/inferred/assumed principled rather than arbitrary.
5. **Use ATL_Fourplex_01 Opt1/Opt2 as the variants-as-deltas case, not NOR Municipal/Tanked** (§5).
6. **Set the accuracy target from Handoff's numbers** (§8): ±25% precision is the industry frontier and human estimators disagree too. Target **±10% on the top-5 carbon drivers, ±25% elsewhere, with honest confidence labels** — and make the *honesty* the selling point, since criterion 3 explicitly rewards saying "data missing" over substituting silently.

Two risks worth naming now: **we have no reference takeoff at all** until either CMHC's Construction Cost Estimates are downloaded (§6) or we build the IFC quantity engine ourselves — and criterion 2 is 30% of the score. And **the sponsor's element list is missing** (§1), so "element list coverage" is currently unscoreable by us.

---

## 12. Immediate actions regardless of the plan

1. **Write `.gitignore` before any `git add`.** 2.7 GB of licence-restricted data is one command away from being committed (§7).
2. Download manually: **Kootenay Material Impact Guide**, **NRC wbLCA Guidelines PDF**, and the **CMHC Construction Cost Estimates / sample LCAs / Materials Guide** (§6).
3. Email the organisers for the **element/material list** and the **wbLCA template** referenced by the scope but absent from the Data Package (§1).
4. `brew install python@3.13 poppler` + venv (§10).

---

# PART 2 — THE PLAN

## Context

We are building an automated takeoff-to-carbon pipeline for the Edmonton Unlimited *Built World Tech* challenge, sponsored by Landmark Homes. A builder's vector PDF plan set goes in; a traceable bill of quantities and an A1–A3 whole-building carbon estimate comes out, with an interface for testing material substitutions. We are scored twice on the same 8-criterion rubric — **Submission 1 on Wed Oct 29** (full product, MVP depth, every criterion addressed) and **Demo Day on Mon Nov 10** — and finally against **Landmark plan sets we will never see before finalist stage**, so generalisation across drawing conventions is the whole game.

**Budget: today is Thu Oct 23.** 6.5 days to Submission 1, then 11 days to Demo Day. At 70 h/week combined that is **~65 h combined for the MVP and ~110 h for depth — ~180 h total.** Owners: **S** = Shiven (CV/perception, geometry, extraction), **T** = teammate (frontend/full-stack, carbon DB, API, UI). Both code everything; the split exists to prevent merge contention, not to silo knowledge.

## Minimum quality bar per criterion

Set now, measured at the Oct 29 and Nov 5 checkpoints. "Good enough to score well" means:

| # | Criterion | W | Minimum bar |
|---|---|---|---|
| 1 | Drawing intake | 10% | Opens any of 53 catalogue sets without crashing; emits a per-sheet inventory with discipline + type; detects and names the 5 toolchain signatures; **gap report lists every unreadable sheet with a reason** (textless, missing schedule, no scale found). |
| 2 | Quantity extraction | 30% | ≥8 element classes; every BoQ line carries sheet + detail provenance and a measured/inferred/assumed label; **median error ≤10% vs IFC on exterior wall area, slab area, roof area, window/door count** across ≥10 designs; human edit recomputes carbon in <1 s. |
| 3 | Carbon + traceability | 15% | Factors in a DB with source/declared unit/geography/validity/data type/**module scope**; zero hardcoded factors; total kgCO₂e + kgCO₂e/m²; contribution analysis by assembly and material; **refuses to sum non-A1–A3 modules**; explicit "no factor found" rows. |
| 4 | Interactive config | 10% | ≥6 real swap options across ≥4 assemblies; result updates live; **substitutions ranked by computed kgCO₂e delta**, not alphabetically. |
| 5 | Usability + automation | 10% | Runs on an unseen set end-to-end in <2 min with no code edits; exportable BoQ (CSV/XLSX) and a PDF/HTML report a builder could hand to a municipality; no LCA jargon unexplained. |
| 6 | Implementation plan | 10% | Written 2-page path to beta with Landmark: pilot scope, integration points, timeline, what we need from them. |
| 7 | Business plan | 10% | Buyer, willingness to pay with a cited comparison, unit economics with real compute costs, competitive wedge vs Handoff/consultants. |
| 8 | X factor | 5% | Published per-category accuracy benchmark + the "we tell you what we can't read" stance as an explicit philosophy. |

**Allocation rule:** after the bars are met, remaining hours go to marginal rubric points per hour in order **2 → 3 → 4 & 5 → 1**. Criteria **6, 7, 8 get a fixed 4 h/week slice** from whoever is less loaded, starting week 1 — not deferred to the final days.

## Architecture and the data contract

```
EmbodiedCarbon/
  ecarbon/
    intake/      open PDF, page inventory, toolchain detect, gap report
    geometry/    path extraction, CTM resolution, scale calibration
    extract/     element detectors, dimension parsing, schedule parsing
    takeoff/     BoQ assembly, assembly resolution, confidence labelling
    carbon/      factor store, provider interface, matching, module guard, totals
    bench/       IFC quantity engine, h2k parser, BPR parser, scoring
    api/         FastAPI
  web/           React (Vite)
  reference/      downloaded guides (gitignored)
  scripts/        fetch_data.py, run_bench.py
  RESEARCH.md
  .gitignore
```

**The one interface that matters** — `TakeoffResult` JSON, frozen at Step 5, is the contract between S's extraction and T's carbon/UI work. Both sides develop against a committed fixture file so neither blocks the other:

```jsonc
{
  "project": { "name", "jurisdiction", "gfa_m2", "gfa_basis", "storeys", "units" },
  "sheets":  [ { "page", "sheet_no", "title", "discipline", "type", "toolchain", "readable", "scale", "scale_source" } ],
  "gaps":    [ { "severity", "code", "message", "page", "affects": ["element_ids"] } ],
  "lines": [ {
    "id", "element_class", "assembly_tag", "material", "quantity", "unit",
    "confidence": "measured|inferred|assumed",
    "basis": { "sources": ["vector_path","dim_text_mm","dim_text_imperial","schedule","h2k","layer_name"],
               "agreement": 0.0, "note": "" },
    "provenance": { "page", "sheet_no", "detail", "bbox": [x0,y0,x1,y1] },
    "assumptions": [ "string" ],
    "user_override": null
  } ]
}
```
Carbon results are a **separate** document keyed by `line.id`, so recomputation never touches extraction output.

---

## PHASE 0 — Foundations (today + Fri Oct 24 am, ~9 h)

**Step 1 — Stop the licence/size hazard.** *(S, 0.5 h)*
Write `.gitignore` (`CMHC Plans/`, `Embodied Carbon Assignment Details/`, `reference/`, `.DS_Store`, `.venv/`, `__pycache__/`, `data/`); move `CMHC Plans/` to `~/ec-data/cmhc/` and reference it via `EC_DATA` env var; confirm the repo is **private**.
*Verify:* `git status --short` shows no data paths; `git add -A && git status` stages <1 MB; `du -sh .git` unchanged.

**Step 2 — Working toolchain.** *(S, 1 h)*
`brew install python@3.13 poppler`; venv; `pip install pymupdf ifcopenshell shapely lxml pydantic fastapi uvicorn pandas openpyxl pytest`.
*Verify:* a script prints PyMuPDF page count + path count for `AB_Fourplex_01_Drawings.pdf` and IfcOpenShell wall count for its IFC, matching this research (46 pages, 92 walls).

**Step 3 — Close the three information gaps.** *(T, 2 h)*
Download the **Kootenay Material Impact Guide**, **NRC wbLCA Guidelines** PDF, and from `housingcatalogue.cmhc-schl.gc.ca` the **Construction Cost Estimates** (these contain published quantity take-offs — §6), sample LCAs and Materials Guide, into `reference/`. Email organisers for the **sponsor element/material list** and **wbLCA template** absent from the Data Package (§1).
*Verify:* `reference/` populated; the Kootenay element priority order is written into `docs/element_priority.md` and drives Step 10's build order; email sent.

**Step 4 — Commit the research.** *(S, 0.5 h)*
Copy Part 1 of this file to `RESEARCH.md`; commit as the first commit on a branch, not `main`.
*Verify:* teammate can clone, read `RESEARCH.md`, run `scripts/fetch_data.py --design AB_Fourplex_01`.

**Step 5 — Skeleton + frozen contract + fixture.** *(both, 5 h)*
Package layout, `pydantic` models for `TakeoffResult`, FastAPI stub with `POST /projects`, `GET /projects/{id}/takeoff`, `POST /projects/{id}/lines/{lineId}`, `GET /projects/{id}/carbon`; Vite+React app that renders a hardcoded fixture end-to-end.
*Verify:* `pytest` green; `uvicorn` serves the fixture; React displays BoQ table + a total from the fixture. **This is the moment the two tracks decouple.**

---

## PHASE 1 — Vertical slice for Submission 1 (Fri Oct 24 – Tue Oct 28, ~56 h)

### S track — extraction (≈30 h)

**Step 6 — Intake + page inventory + toolchain detection.** *(S, 4 h)*
Per page: size, path/text/image op counts, OCG layer names, Revit metadata keys, `/VP` presence. Classify toolchain into `revit_tagged | aia_layered | flattened | distiller_outlined | vectorworks`.
*Verify:* run across all 53 sets; output matches the §2 table (NOR's 8 sets classify `distiller_outlined`; ATL/BC classify `aia_layered`); **zero crashes**.

**Step 7 — Sheet classifier + gap report.** *(S, 4 h)*
Three-rung ladder: Revit page metadata → title-block text near the sheet-number box → LLM classification of extracted title text (structured output, schema-validated — per CEQuest failure mode 1). Emit `gaps` for textless pages and missing sheet types.
*Verify:* **the `List of Drawings` PDFs are free labelled ground truth for 51 of 52 designs** (§4/§6) — parse them into `bench/sheet_truth.json` and score. Bar: **≥90% exact sheet-number match and ≥85% type match on 10 designs**; all 8 NOR sets flagged "titles unreadable" rather than guessed.

**Step 8 — Scale calibration.** *(S, 5 h)* ← *highest-risk unlock*
Resolve full CTM per path. Three scale sources, in order: `/VP` viewport matrix (§4d, needs empirical calibration), parsed `SCALE: 1/4" = 1'-0"` text, and ratio of a parsed dimension string to the measured geometry span it annotates.
*Verify:* on 5 designs, scale derived from each available source agrees within **1%**, and a measured overall building footprint matches the IFC footprint within **2%**. **If `/VP` cannot be calibrated in 2 h, drop it and rely on sources 2 and 3** — note it in the gap report as reduced confidence.

**Step 9 — Ground truth store.** *(S, 7 h)*
IFC quantity engine (walls from `IfcExtrudedAreaSolid`+`IfcRectangleProfileDef`, fallback `IfcFacetedBrep` volume; areas/volumes per element and per `IfcMaterialLayerSet` layer); HOT2000 XML parser (wall/ceiling `area`, slab perimeter, window count); BPR parser (EC total, EC/GFA, GFA — already proven on 71/73).
*Verify:* IFC-derived exterior wall area agrees with HOT2000 `<Measurements area>` within **15%** on ≥6 designs (they measure slightly different things; large disagreement means a bug). Mark the 7 SKMB and 6 NOR `_Tanked` designs `ground_truth: unusable` (§5).

**Step 10 — Wall + slab + roof takeoff v1, Alberta only.** *(S, 10 h)*
Build order from the Kootenay guide (Step 3), defaulting to: **foundation/slab concrete → exterior wall assembly end-to-end → roof → floors → windows/doors**. Exterior wall = closed-polygon detection on wall-weight paths, paired-line thickness, storey heights from section datums (`T/O F/F SECOND 3.000 m`), openings subtracted. Assembly tag (`W2`, `F1`, `R2`) attached from nearest section/plan tag.
*Verify:* on **AB_Fourplex_01, AB_Fourplex_02, AB_Sixplex**: exterior wall area, slab area, roof area each within **15%** of the Step 9 IFC truth; every line has `provenance.page` and a confidence label. Dual-unit agreement (mm vs ft-in, §4e) drives `measured` vs `inferred`.

### T track — carbon + UI (≈26 h)

**Step 11 — Factor store + provider interface.** *(T, 5 h)*
SQLite/DuckDB table: `material_key, name, source, source_id, declared_unit, density_kg_m3, gwp_value, gwp_unit, modules[], geography, validity_from/to, data_type(epd|industry_avg|generic), uncertainty_pct, attribution`. `FactorProvider` ABC with `LocalSnapshotProvider` now, `EC3Provider` stubbed. Seed from **BEAM** (A1–A3, Canadian, low-rise residential — the right fit, §9) plus an attributed EC3 snapshot for the top materials; **do not use ICE** (commercial use prohibited).
*Verify:* `grep -rn` finds **zero numeric factors in application code**; a test asserts every row has non-null source, declared unit, geography and modules; a test asserts loading a non-A1–A3 record and summing it **raises**.

**Step 12 — Matching, unit reconciliation, totals.** *(T, 6 h)*
Map `CMHC_*` material names (§5 — standardised across the whole catalogue, so one table covers it) to factor keys. Reconcile declared units (m³/m²/kg/each) against BoQ units via density. Compute total kgCO₂e, intensity per m² GFA, contribution by assembly and by material category. Formula and A4–A5 extension points per IStructE: `EC = Σ(qty × ECF)`, `A5w = WF × (A1–A3 + A4 + C2 + C3–C4)` (§9).
*Verify:* unit-conversion test suite; an unmatched material produces a visible `"no factor found"` row that is **excluded from the total and reported**, never silently zeroed; contribution percentages sum to 100%.

**Step 13 — API + BoQ export.** *(T, 4 h)*
Wire the four endpoints to real data; CSV/XLSX export with provenance columns.
*Verify:* `curl` upload of `AB_Fourplex_01_Drawings.pdf` returns a takeoff and a carbon result; exported CSV opens in Excel with sheet/detail columns populated.

**Step 14 — UI: the whole loop.** *(T, 11 h)*
Upload → project-facts prompt (conditioned floor area basis, jurisdiction, known specs — Stage 1 requirement) → gap report panel → BoQ table with confidence chips and assumption tooltips → totals + intensity → contribution chart → editable quantity cells → swap panel.
*Verify:* a person who has not seen the code uploads a set, reads the total and intensity, edits a wall area, and sees the total change — **without being told how**.

### Integration

**Step 15 — Substitution ranking.** *(T, 3 h)*
≥6 swaps (cellulose↔spray foam, fibre cement↔vinyl, standard↔low-carbon concrete mix, window frame types), each a factor-store row; rank by computed Δ kgCO₂e using Step 12's contribution analysis.
*Verify:* ranking order changes correctly when the underlying quantity is edited.

**Step 16 — End-to-end + benchmark v1 + Submission 1.** *(both, 8 h; Oct 28–29)*
`scripts/run_bench.py` producing median / worst-case / spread per element class, grouped by toolchain. Write the Submission 1 package: 2-page implementation plan, business plan, benchmark table, demo video if required.
*Verify:* one command runs 3 AB designs and prints the benchmark table; a fresh clone + `fetch_data.py` + `uvicorn` works on the teammate's machine.

> ### ⛳ CHECKPOINT A — Wed Oct 29
> Score ourselves against the 8 bars. Decision rules:
> - **Criterion 2 median error >25% on wall area** → stop adding element classes; spend Oct 30–Nov 1 entirely on wall accuracy. A broad-but-wrong takeoff scores worse than a narrow-but-right one (the scope says so explicitly).
> - **Scale calibration still unreliable** → fall back to schedule-and-stated-totals extraction for area, and say so in the gap report. Do not ship guessed scale.
> - **UI loop not closed** → T drops the contribution chart and PDF report styling until the edit→recompute path works.
> - Anything else behind → cut lowest rubric value first, re-measure, don't re-plan.

---

## PHASE 2 — Depth and differentiators (Oct 30 – Sun Nov 9, ~110 h)

Ordered by marginal rubric points per hour.

**Step 17 — Widen to 10–15 designs across toolchains; split by toolchain not region.** *(S, 10 h)*
Dev/validation/held-out drawn from the **39 usable designs**, grouped by detected toolchain (§11 adj. 2): **dev 20, validation 9, held-out 10**. SKMB (7) + NOR-textless (8) form a separate **robustness suite** scored on "correctly reported what it could not read", not on quantity error. Touch held-out **≤3 times total**.
*Verify:* benchmark reports median, worst case and spread **per toolchain group**; no single average.

**Step 18 — Accuracy push on the top carbon drivers.** *(S, 20 h)*
Concrete (foundation walls, footings, slab), exterior wall assembly layer-by-layer, roof. Use the **~20 layer-labelled sets to auto-generate element labels** and validate the geometry-only classifier that must work on the other half (§4c) — the strongest idea in the research.
*Verify:* median ≤10% on the four headline quantities across ≥10 designs; worst case ≤30%; **held-out touch #1**.

**Step 19 — Assemblies + openings schedule parsing.** *(S, 8 h)*
Sheets `A003 ASSEMBLIES SCHEDULE` and `A004 OPENINGS SCHEDULE` exist consistently. Parse into layer build-ups and window/door schedules; cross-check against IFC `IfcMaterialLayerSet`.
*Verify:* parsed build-up for `W2` matches the IFC layer set (materials and thicknesses) on ≥5 designs.

**Step 20 — Click-to-trace.** *(both, 10 h)* ← *the demo moment*
Click a BoQ line → render the source page and highlight `provenance.bbox`.
*Verify:* 10 random lines each highlight a region that genuinely contains the measured element.

**Step 21 — Uncertainty ranges + sensitivity ranking.** *(T, 8 h)*
Propagate factor `uncertainty_pct` (EC3 primer confirms EPD GWP carries statistical ranges, §9) and quantity confidence into a result range; rank which assumptions move the total most.
*Verify:* the published CMHC total for a design falls inside our A1–A5-adjusted band; sensitivity top-3 are stable across reruns.

**Step 22 — Module-scope reconciliation view.** *(T, 5 h)*
Show our A1–A3 beside the CMHC published A1–A5+B+C total with the module difference stated. **This is criterion 3's discipline made visible** (§6).
*Verify:* the view refuses to present the two as comparable and labels both module sets.

**Step 23 — Variants as deltas.** *(S, 8 h)*
Use **ATL_Fourplex_01 Opt1/Opt2** (not NOR Municipal/Tanked, §5) and a mirrored plan.
*Verify:* the second variant processes reusing the base takeoff, reporting only changed lines, in <30 s.

**Step 24 — OCR fallback for the 8 textless NOR sets.** *(S, 10 h)* — *first cut candidate*
Render page regions, OCR dimension strings and titles, feed the same ladder at lower confidence.
*Verify:* ≥50% of NOR sheet titles recovered; everything unrecovered still appears in the gap report.

**Step 25 — Report output + polish.** *(T, 8 h)*
Builder-facing PDF/HTML report: totals, intensity, contribution, assumptions, gaps, factor sources with attribution.
*Verify:* a non-LCA reader can explain the number from the report alone.

**Step 26 — Published benchmark page.** *(T, 4 h)*
Per-category accuracy by toolchain group. **Statistics are not redistribution of CMHC data** (§7) — safe to publish.

> ### ⛳ CHECKPOINT B — Wed Nov 5
> Freeze features. Nov 6–9 is rehearsal, bug-fixing and **held-out touch #2 and #3 only**. Anything not working on Nov 5 is cut, not fixed.

**Steps 27–29 — Running in parallel, 4 h/week from Oct 24 (whoever is less loaded).**
- **27, Implementation plan to beta with Landmark:** pilot on 3 Landmark plan sets → calibrate against their reference takeoffs → 2-week accuracy report → integration with their estimating workflow → named asks (plan sets, one estimator for 2 h/week, their material/supplier list).
- **28, Business plan:** buyer = production builder's estimating/sustainability lead (scope: 100–800 homes/year on standardised plans). Willingness to pay anchored on the status quo — weeks and thousands of dollars per consultant assessment, versus **a per-plan baseline that amortises across every home on that plan**. Pricing: ~$1k–2k per plan baseline or $20k–40k/yr enterprise. Unit economics: marginal compute per plan is PDF parsing plus bounded LLM calls — single-digit dollars — so gross margin is very high and the cost is sales, not serving. Wedge: carbon is the regulatory forcing function (federal Standard on Embodied Carbon, amended Mar 2025, effective Sept 2025); expansion is **takeoff → cost estimating**, a far larger market. Competitive line vs **Handoff-H1** (81.6% composite, §8): they do multi-trade cost takeoff with no carbon layer, no traceability, no module discipline, no gap reporting.
- **29, Pitch + X factor:** narrative mapped criterion by criterion; the honesty stance ("we tell you what we cannot read") as an explicit philosophy, backed by the NOR textless case.

---

## Demo Day: what to show live, in order

1. **Upload an unseen set** (held-out) — timer visible. Hits criteria 1 and 5.
2. **Gap report first, before any number.** "Here are four things we could not read, and here is why." Nobody else will lead with this.
3. **BoQ with confidence chips** → **click a line, the source sheet highlights.** Criterion 2, the memorable moment.
4. **Edit one wall quantity** → total moves live. Criterion 2's explicit requirement.
5. **Total + intensity, then the module reconciliation** against CMHC's published figure. Criterion 3.
6. **Contribution analysis → ranked substitutions → swap the concrete mix**, total drops. Criterion 4.
7. **The benchmark table**, by toolchain group, including worst case. Criteria 8 and 5.
8. Close on implementation plan and business model. Criteria 6 and 7.

## Top risks

| Risk | Likelihood | If it hits |
|---|---|---|
| **No reference takeoff exists** — 52/53 IFCs have no quantities (§5) and CMHC's cost estimates may not be downloadable | High | Step 9's IFC quantity engine *is* the mitigation and is scheduled first. If it slips, benchmark against HOT2000 areas + BPR totals only, and say so. |
| Scale calibration unreliable (`/VP` convention unknown, §4d) | Medium | Step 8 has a 2 h timebox and two fallbacks. Worst case: extract from schedules and stated totals, report reduced confidence. |
| Wall polygon detection fails on `flattened` toolchain sets (no layers, no Revit tags) | Medium-high | Use the layer-labelled sets to train/validate the geometric classifier (Step 18). If still failing, restrict confident output to `revit_tagged` + `aia_layered` and gap-report the rest honestly. |
| Sponsor element list never arrives (§1) | Medium | Proxy from the Kootenay guide + CMHC assembly schedules; state the assumption in the submission. |
| 18 days is not 8 weeks | Certain | Checkpoints A and B with cut-lowest-value-first rules. |
| CMHC data accidentally committed | Low after Step 1 | Step 1 is first for this reason. |

## What will not fit in 180 h — stated plainly

Full element-list coverage (we will cover ~8–10 classes, not every assembly); a trained ML element classifier (rule-based plus layer-derived labels only); live EC3 API at scale (cached attributed snapshot behind a provider interface — which is what the scope actually asks for); **A4–A5 implemented** (architecture and extension points only, as the scope permits); DWG ingestion (deliberately dropped, §7); a benchmark across all 39 usable designs (expect 10–20); and productionised OCR for the 8 textless NOR sets (Step 24 is the first thing to cut). Honest assessment: **criteria 2 and 3 can genuinely reach the bar; criterion 1 will be strong because the gap report is cheap and distinctive; criterion 4 will be real but shallow; the 25% in criteria 6–8 is won by writing, which is why it gets a weekly slice from day one.**

