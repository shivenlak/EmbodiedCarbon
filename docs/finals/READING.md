# Stream A: `finals/reading`. "Reads any plan set, anywhere"

Owner: **Divyesh**. Read [SHARED.md](SHARED.md) first: the rules, file ownership, contracts C1–C6, and the blind protocol all apply.

**Goal:** a plan set from any country, drawn in any convention, metric or imperial, vector or scanned, comes out with a bill. Where the tool can't read something, it says so rather than guess.

**You own:** `ecarbon/extract/*`, `ecarbon/geometry/*`, `ecarbon/intake/*`, `ecarbon/vision/*` (new), `gather()` and line building in `ecarbon/takeoff/builder.py`, `scripts/score_blind.py`, `corpus/dev_truth.yaml`.

**You never open holdout sets.** Fetch with `--split dev` only.

Tick each box in the PR that lands it.

---

## A1. Corpus, scoring, failure list (Thu 19 – Fri 20)

- [x] `python scripts/fetch_corpus.py --split dev` fetches into `~/ec-data/global/`.
- [x] **Dev truth.** *(4 Escondido sets; the two AU sets need a browser download, then truth)* Write `corpus/dev_truth.yaml`, one entry per dev set, about 15 minutes each, read by eye off the drawings:
  ```yaml
  us-boise-adu-1:
    footprint_m: [7.32, 9.75]      # W x D from the overall dimension strings, converted
    storeys: 1
    storey_heights_m: [2.74]       # plate height per storey
    windows: 9
    doors: 3
    exterior_wall: "2x6 @ 16\" O.C., R-21 batt, 1/2\" OSB, lap siding"
    notes: "dims in feet-inches; sheet A2.1 has the sections"
  ```
  - Facts only; no drawings in git.
  - Record `null` where the set doesn't state something. Concept sets won't have wall types.
- [x] **`scripts/score_blind.py`**:
  - `score_set(design_dir, truth) -> dict` (the C6 row) runs `config.pdf_designs(dir)` then `build_takeoff`, and scores each stage:
    - sheets classified
    - a trustworthy scale found
    - footprint error %
    - storeys right
    - height error
    - assemblies found
    - opening count error
    - coverage via `builder.coverage_report`
  - Every failure is a readable `broke` string.
  - CLI: `python scripts/score_blind.py --split dev` writes `out/blind.json` and prints a table.
  - B imports `score_set`, so keep it import-safe: no work at import time.
- [x] **C1 stub.** `ecarbon/intake/locale.py` with the `Locale` dataclass and `detect_locale()` returning all-`None`. PR it on day 1 so B can build against it. Tick C1 "stub" in SHARED.md.
- [x] **Baseline.** *(23 Nov, on Divyesh's machine, which has the catalogue too: 52 designs, median coverage 83%, median 23.8 s per design; the 8 image-only NOR sets produce nothing. `out/baseline.json`, local only.)* Run `scripts/run_pipeline.py` on CMHC and save `out/baseline.json`. If `--json` doesn't exist yet, add a minimal one: per design, coverage % and total. This is the "must not regress" line.
- [x] **Failure list.** Rank the `broke` strings across dev sets by how many sets each one blocks. Paste the top 10 into this file under "Findings". That list orders A3.

## A2. `intake/locale.py`, the real version (Fri 20)

- [x] **Unit system:** *(a bare number under 1000 casts no vote: US sheets are full of "24" and "250" that parse as mm)*
  - Vote across dimension labels using `DimLabel.unit_system` (`geometry/scale.py`, collected by `calibrate()`), plus the style of scale notes (`1:100` vs `1/4" = 1'-0"`).
  - Return `"metric"`, `"imperial"` or `"mixed"` (dual-dimensioned, as CMHC sets are), with counts in `evidence`.
- [x] **Country and region** *(CA/US/AU by state or province via `region.from_text`, on 2+ sheets and 2:1 over any other country; GB/IE/NZ/IN/EU stay hints only until a dev set exists to test them on)* from the title-block and cover-sheet text. Use the same span reading as the rest of the code (`intake/spans.read_spans`).

  | Country | What to match |
  |---|---|
  | US | state abbreviation + 5-digit ZIP (`Boise, ID 83702`) |
  | CA | province + `A1A 1A1` postcode |
  | GB | UK postcode (`SW1A 1AA`) |
  | IE | Eircode |
  | AU | state (`VIC`, `NSW`, …) + 4-digit postcode |
  | NZ | NZ region names |
  | IN | 6-digit PIN + state name |
  | EU | country names; `Maßstab`/`échelle` scale words as a hint |

  - Low-confidence hints go into `evidence` but return `None`. Don't guess a country from one weak hint.
- [x] **Wire it in:** *(`builder.mark_units`; the info gap uses `GEOMETRY_AMBIGUOUS` since models.py is frozen)*
  - `build_takeoff` calls `detect_locale` once.
  - The `BasisSource.DIM_TEXT_METRIC` hard-codes in `builder.py` become `DIM_TEXT_IMPERIAL` where the set is imperial.
  - Add an info gap when imperial: "drawn in feet and inches; quantities converted to SI".
  - CMHC sets are `mixed` and must keep their sources and totals.
- [x] Unit tests: one per pattern, plus a CMHC set reading `CA` / `mixed`. Tick C1 "real".

## A3. Rules for global drafting conventions (Sat 21 – Sun 22)

Work in the order of the A1 failure list. Each new pattern gets a unit test, and **the Alberta gate must not move**.

- [x] **`extract/levels.py`:** *(24 Nov: datums printed with their label in one span; relative `100'-0"` works because only differences are used; a bare AU `RL` is refused, it needs `FFL RL`)*
  - feet elevations: `T.O. PLATE 9'-1 1/8"`, `TOP OF PLATE EL. 109'-1"`, `FIN. FLR. EL. 100'-0"`
  - relative datums such as `100'-0"` taken as ±0
  - AU `RL 12.450` (reduced levels)
  - UK `FFL +3.000` / `SSL` / `TOS`
  - DE `OKFF ±0,00`
  - Reuse `scale.parse_imperial`. Keep the plate-vs-ridge distinction (`roof_level_m`).
- [x] **`extract/specs.py`:** *(24 Nov: all slab and footing forms read, plus `8" CONC. FOUNDATION WALL` and a stated foundation wall height; rebar notes `#4 @ 12"` / `N12-300` not read, as no quantity uses them)* `4" CONC. SLAB ON GRADE`, `16" x 8" CONT. FTG`, `#4 @ 12" O.C.`, `N12-300` (AU rebar), `150 THK SLAB`, `100mm thick`.
- [ ] **`extract/assemblies.py`:** *(24 Nov: nominal lumber, AU/UK depth-first and spacing-based framing share done; decimal comma not)*
  - [x] Nominal lumber: 2x4 → 89, 2x6 → 140, 2x8 → 184, 2x10 → 235, 2x12 → 286 mm. Also AU/UK `90x45` / `140x45` (stud depth is the first number).
  - [x] Framing fraction from the stated spacing: `@ 16" O.C.` / `@ 24" O.C.` / `@ 400 crs` / `@ 600 crs`. Use the spacing to compute stud share instead of always `FRAMING_FRACTION = 0.15`; the no-spacing case keeps 0.15, so CMHC is unchanged.
  - Decimal comma (`2,40`).
  - US wall-type legends that are a list of notes rather than a layer table. *(done 23 Nov: `legend_assemblies_on_page`, Escondido and Santa Cruz format)*
- [ ] **`extract/openings.py`:** *(24 Nov: no `3068`-style door code occurs in the dev or Landmark corpus, so not built; plans with no schedule now read each opening's width-over-height label, see Findings)* imperial as primary when there's no metric column; `3068` / `2868` / `2668` door codes (W×H in feet-inches); tags `W-1`, `W01`, `D1`, `101A`.
- [x] **`intake/classify.py`:** *(24 Nov: all listed numbers and titles type; ISO 19650 added; a title-block-column title now beats a nearer drawing heading)*
  - US `A-101`, `A2.1`, `S-1`, `G-001`
  - UK BS 1192 / ISO 19650 numbering (`PRJ-XX-ZZ-DR-A-1001`)
  - AU `DA-01` / `CC-101`
  - titles such as "BUILDING SECTIONS", "WALL SECTIONS", "WALL TYPES", "DOOR & WINDOW SCHEDULE", "GENERAL ARRANGEMENT", "GROUND FLOOR PLAN", "FIRST FLOOR PLAN" (= the second storey in UK/AU usage!)
- [x] **`geometry/scale.py`:** *(24 Nov: all listed forms already parse; `NTS` gives no scale)* `1:100 @ A1`, `1:100 @A3`, `SCALE: 1/8" = 1'-0"` spacing variants, `NTS` as "no scale". Graphic bar scales only if cheap.
- [ ] **The old `feat/pipeline-improvements` work** (tag `archive/pipeline-improvements`):
  - It merges cleanly into `main` and keeps the Alberta gate.
  - But it makes `BC_Duplex`'s exterior wall parse where `main` refuses it as unreliable, so `tests/test_assemblies.py::TestAcrossFirms::test_an_unreliable_parse_is_reported_rather_than_used` fails.
  - **Optional:** check the BC_Duplex read against its IFC layer set (`scripts/score_assemblies.py`). If it's right, bring the commits in and update that test with the evidence. If not, leave it archived.
- [ ] After A3: rerun `score_blind.py --split dev` and `run_pipeline.py`. Record before/after under "Findings".

## A4. `ecarbon/vision/`, a fallback only where the rules failed (Sat 21 – Mon 23)

**Principle:** the rules run first and stay the source of truth. Vision only runs where the rules came back empty, and every vision value must prove where it came from.

- [ ] **Triggers** (computed in `gather()`; already cheap to detect):
  - sheets with `readable=False` or toolchain `RASTER` / `DISTILLER_OUTLINED` (`intake/inventory.py`)
  - `footprint is None`
  - empty `assemblies_for` or `openings_for`
  - `spec.missing`
  - `heights.missing`
- [x] **`vision/providers.py`:**
  - One interface: `read(png: bytes, task: Task) -> dict | None`.
  - Two adapters: `ClaudeProvider` and `GeminiProvider`. **Load the `claude-api` skill before writing the Claude adapter**, and use the current model ID and its structured-output/tool-use pattern.
  - Selected by `ECARBON_VISION=claude|gemini`, with keys from `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Unset means vision is off and behaviour is exactly as today.
  - Add the SDKs as an optional extra in `pyproject.toml` (`[project.optional-dependencies] vision = [...]`), imported lazily.
- [ ] **`vision/tasks.py`:** (1–4 done: sheet, scale, footprint, levels; footprint and levels feed the takeoff) one pydantic answer schema plus a prompt per task, in priority order:
  1. sheet type and number
  2. scale note
  3. overall footprint dimensions (from dimension strings, not by measuring pixels)
  4. level datums / storey heights
  5. wall-type / assembly schedule
  6. window and door schedule

  Every field carries `quote` (the verbatim text it was read from) and `box` (pixel bbox). Every schema allows `found: false`, and the prompt says plainly that "not on this sheet" is the right answer when it isn't there.
- [x] **`vision/validate.py`, quote-and-locate:**
  - Convert the box from pixels to PDF points (render DPI and page rotation; see how `trace.render_page` renders).
  - **Vector pages:** the quote, normalised, must be found in the page's own text (`read_spans`) within or near the box. Otherwise the answer is **dropped** and the drop logged.
  - **Raster pages:** there's no text to check, so the value is kept but capped at `INFERRED`, with the note "read from an image; not verifiable against text".
  - Numbers in the answer must parse out of the quote with the existing parsers (`parse_dimension`, `parse_scale_text`, `parse_imperial`). The model's own arithmetic is never trusted.
- [x] **`vision/cache.py`:** a disk cache in `~/.cache/ecarbon/vision/` keyed by `sha256(png + task + PROMPT_VERSION + provider/model)`, plus a page budget per upload (env `ECARBON_VISION_MAX_PAGES`, default 12).
- [ ] **Into the takeoff:**
  - Results fill `TakeoffInputs` (scale → `ScaleEstimate`, footprint → `Footprint`, levels → `StoreyHeights`, schedules → `Assembly` / `Opening`), so line building is unchanged.
  - Labels per **C3**: `"vision: "` note, an `assumptions` entry, and `Provenance.bbox`. The trace highlight then works by itself, because `trace_line` honours `bbox` first.
  - Emit `progress("vision", ...)` (**C4**).
- [ ] **Cross-check:** where the rules and vision both answer, agreement goes in the note ("agrees with the dimension chain"), and disagreement becomes a WARNING `Gap` with both values. Never silently resolved.
- [x] **Tests:** recorded provider responses under `tests/fixtures/vision/`. CI never calls an API. Test that the validator drops a hallucinated quote, and that vision-off leaves CMHC totals bit-identical.
- [ ] **Provider bake-off (Mon 23):**
  - Run both providers on every dev set.
  - Per provider, record: answers accepted by the validator, answers right against `dev_truth.yaml`, wrong answers that got through, answers dropped by the validator, $ per set, and seconds per set.
  - Choose the default by **accepted-and-right per dollar**. Put the table under "Findings"; it goes in the deck.

## A4b. Plan sets delivered as several PDFs (Landmark), by Mon 23

Landmark delivers each project as separate PDFs: Floor Layout, Roof Layout, Building Details, Schedule A, Final Blueprint, Foundation, and Mech & Electrical. See SHARED.md "Landmark Homes sets" for the **confidentiality rules**: vision is allowed, but nothing goes in git.

- [x] **One design from a folder.** `config.pdf_designs(folder)` (or a new `folder_design`) makes **one** `Design` from all the PDFs in a folder, so the inventory sees every sheet across every file. Pages need a stable global index, plus a `(file, page)` mapping for provenance and trace. Check how `Design.drawings_pdf` is used (`config.py:44`, `intake/inventory.py`, `trace.render_page`), and keep single-PDF behaviour unchanged.
- [x] **Sheet classification across files.** File names are a strong hint ("Foundation.pdf", "Roof Layout.pdf"). Use them only when the title block is unreadable, and record that as the basis.
- [x] **Skip trades we don't count.** Mechanical/electrical sheets are recognised and skipped, with an info note.
- [x] **Score the Landmark sets** with `score_blind.py` (rules only), using `~/ec-data/landmark/` as a dev source. Put the "what broke" items into the A3 queue. Scores go in Findings without any Landmark quantities quoted.
- [x] **Hand-off for B2b:** tell B the function to call, e.g. `folder_design(path) -> Design`, under Requests in SHARED.md.

## A5. Image-only sets (Tue 24)

- [ ] Run vision on the 8 NOR CMHC sets with no text, and on any image-only sets in the dev corpus. **Target:** "nothing read" becomes a bill with every line `INFERRED` and traced. Record before/after.
- [ ] Make sure these sets still say plainly that the values were read from an image.

## A6. Hardening and numbers (Wed 25, freeze at end of day)

- [x] Rerun `score_blind.py --split dev` and `run_pipeline.py --json`. Fix the top regressions. CMHC coverage must be at or above `out/baseline.json`. *(24 Nov: no set down, mean 67.6 -> 79.6%; see Findings.)*
- [x] Hand B the numbers (under "Findings"): CMHC coverage before → after, dev stage scores before → after, the bake-off table, and NOR before → after. *(Rules-only numbers given 24 Nov; the bake-off and NOR need a vision key.)*
- [ ] Freeze. After this, bug fixes only.

---

## Findings (append as you go)

- *(A1 failure list, A3 before/after, A4 bake-off, A5 NOR before/after)*
- **23 Nov, A2 locale on every local set:** all 44 text CMHC sets read `mixed`; region is right on every AB, BC, ON, QC, SK/MB set and on NOR's garage set (CA-NT). ATL and the 8 image-only NOR sets name no region (no state or province on 2+ sheets). All 10 US dev sets read `imperial` / `US-CA`; AU sets read `metric` with no region (no `VIC 3000`-style address in their title blocks). Cost: 12 sampled sheets, 1–5 s per set, almost all of it PyMuPDF text extraction; cached per file.
- **19 Nov, Landmark baseline (rules only, main @ dc8df88): 0 quantities on all three projects. This is the top priority.**
  - Not one sheet is classified: 0/13 (RPL), 0/14 (RSL) and 0/11 (Townhome blueprint) are `unknown`, and 0 scales are found. So every downstream extractor reports "no floor plan / section / schedule".
  - **Why:**
    - The title block has a "SHEET n NO." layout (the number reads *before* the words) and an empty-looking "DRAWING:" field. Neither `classify_page` nor `from_title_block` matches it.
    - There are no written scale notes.
    - Dimensions are feet-and-inches only.
  - **Implications:**
    - (1) Classify from the drawing content (view titles inside the sheet, e.g. "...FLOOR PLAN", "SECTION", "ELEVATION") when the title block gives no title. This is also vision task 1.
    - (2) Scale must come from dimension chains in feet-inches (`parse_imperial` already exists), or from vision task 2.
    - (3) This is A4b's multi-PDF case: Townhome's foundation sheet is a separate PDF **with no text layer**, a natural first vision target.
  - Inspect the files locally in `~/ec-data/landmark/`. Don't paste their text into the repo.
- **19 Nov, A1 failure list, dev split (4 Escondido ADU sets, US, imperial):**
  - Before the US title-block fix, 0 sheets were typed on all four. After, 82% of readable sheets are (sheet numbers `A-901`, `A3-101`, `T24-301`; titles set vertically).
  - Still 0 quantities on all four. Every one of these blocks all four sets:
    1. `sheets: no section classified`: sections share "ELEVATIONS & SECTIONS" sheets, which type as elevation.
    2. `sheets: no assembly schedule classified`: the wall types are a legend of notes on the floor plan.
    3. `levels: no floor datum read`: the datum is `PLATE HEIGHT 8'-1"`.
    4. `foundation: slab thickness not stated`: it says `4" CONCRETE SLAB ON GRADE`.
    5. `openings: no schedule read`: there are window and door schedules on the floor plan sheet.
    6. `assemblies: none read`.
  - `footprint: area off by more than 10%` on 3 of 4 (+377 to +543%). Correction: the takeoff did *not* refuse these footprints. They reached the bill (fixed below).
- **19 Nov, Escondido fixes (blockers 1 and 3, plus footprint and scale):**
  - A combined "ELEVATIONS & SECTIONS" title now types as section.
  - Imperial datums (`10'-1 1/2"`, signed inches) pair with their labels. A one-storey set takes its height from the top-plate datum.
  - Footprint: a sheet that draws the main plan beside option vignettes in one stroke now offers the largest drawing as a candidate, but only at the winning lineweight or heavier.
  - Scale: a stated scale can promote a secondary dimension cluster that it agrees with.
  - Result: all 4 footprints within 0.4% of the dimensioned truth (were +377 to +543%). All 4 read 1 storey at the plate height.
  - CMHC: Alberta gate unchanged. IFC footprint median error 3.3% → 3.3%. The only scoreable design that moved is NOR_ADU_Municipal_Garage, whose IFC box (72 × 106 m) is the site rather than a building. It was wrong before and is still wrong. A ceiling datum (`2546 CEILING`) is no longer read as a floor.
  - CMHC coverage (`run_pipeline.py`, main → branch): no set dropped. SKMB_Fourplex_01 and _02 went 0% → 9% (quantities produced at all). SKMB footprints are now the building, not the site.
  - Partitions: the footprint now carries its page outline, and a wall outside it (a fixture legend beside the plan) no longer counts. Runs along the perimeter are kept: the Alberta IFC partition lengths in `test_partitions.py` include them, and dropping them took the median error from ≤8% to 30%.
  - **Known overcount:** BC_ADU_02 A102 partitions read 80.5 m (main: 1.1 m). Its footprint is now right (5.6 × 8.8 m; main read 31.9 × 20.9 m), but at that lineweight the perimeter runs count. The total without partitions is unaffected. No IFC partition truth outside Alberta to settle it.
  - Dev score after: Escondido within 4.4%. Riverside 1/3/4 footprints are wrong (+72%, +658%, +61%): a detection that succeeds wrongly, so vision (which only runs on no footprint) will not catch it. Next footprint task.
- **20 Nov, Riverside footprints (a detection that succeeded wrongly):**
  - Cause: the sheet draws its plan twice. Labels that line up across both copies were summed into one "chain" (drawn span 1.15–5.6× its total), and the outline spanning both copies matched those sums. The 17'-0" and 40'-0" overall dimensions are single labels outside the wall line, which never counted.
  - Fix (`geometry/footprint.py`): a chain is split wherever two neighbouring labels are not drawn end to end at the page scale. A single label counts for a candidate's side when it sits within 3 m outside that side and is centred on it (3%).
  - Dev: Riverside 1/2/3 at −0.3/+1.3/+0.8% (were +72/+1.3 by luck/+658%). Riverside 4 reads its 40'-0" × 31'-0" overall exactly; the +37% area left is the L shape against a rectangle. Riverside coverage 0% → 13%.
  - CMHC: Alberta gate unchanged. IFC footprint median 3.3% → 3.1%, within 5% 24 → 25 of 38; ATL_ADU_02 5.7 → 0.0%, QC_ADU_02 2.3 → 0.0%; no scoreable set worse. Dimension agreement on the chosen footprint is now ≈0% on most sets (was 1–7%).
  - Partitions use one wall stroke per set (the commonest across floors, ties to the heavier). QC_ADU_02's main floor found its outline in a 0.48 line that also draws fixtures (89 m of partitions; now 2.6 m at 1.32).
  - Partition changes, all explained: BC_ADU_02 A102 80.5 → 11.5 m (the known overcount, fixed). ON_ADU_01 42.7 → 20.8 m (it was measured against a 30 × 25 m sheet outline). Second floors that read near nothing now read: BC_Rowhouse A102 37 m, QC_Fourplex_01 A101 5 → 59 m, QC_Rowhouse_01 A102 2 → 32 m.
  - CMHC coverage (`run_pipeline.py`, main → branch): no set moved. Carbon moved on the sets above, plus NOR_ADU_Municipal_Garage (footprint 5.0 × 6.6 → 7.3 × 8.3 m; its IFC box is the site, so unscoreable either way).
- **20 Nov, imperial slab (A1 blocker 4):**
  - `extract/specs.py` reads `4" CONCRETE SLAB ON GRADE` / `4" CONC SLAB W/ #4 @ 18" O.C.` as 102 mm. CONC is required next to the figure, so a cover note (`2" CLR CVR @ 4" SLAB`) is refused.
  - When the structural sheets state no slab, the slab alone (not beams or footings) is read off the other sheets: Escondido-2/4 state it in an A-sheet keynote, and Riverside's sheets carry no sheet numbers. An unnumbered sheet (`p9`) now traces to its own page.
  - Dev: slab read on 6 of 15 sets (was 0), all 102 mm against truth 102. Riverside coverage 13% → 31%. Escondido-1/3 still say "per structural" with no figure, which is right.
  - Alberta gate unchanged.
- **20 Nov, US opening schedules (A1 blocker 5):**
  - `extract/openings.py` gains `header_schedule_on_page`: a WINDOW/DOOR SCHEDULE whose columns are named by a header row (WIDTH, HEIGHT, QTY). Feet-inches cells split across two spans (`3'-` over `0"`) are rejoined; side-by-side tables are bounded by x; a table ends at its first row break. It runs only where the CMHC reader finds nothing.
  - Count: the schedule's QTY column where there is one. A numbered schedule (door 1, 2, 3) counts each row once, stated as an assumption on the line. Lettered types with no quantity are not counted, and each gets a gap. Plan tags are not counted for US sets: a bare "A" cannot be told from every other "A" on the sheet.
  - Dev: openings read on 10 of 15 sets (was 0). Opening error (|windows| + |doors| against truth): Escondido 13/16/21/21 → 1/7/0/1; Riverside 11/13/14/17 → 0/1/7/3; Santa Cruz 13/18 → 2/13. Coverage: Escondido 68 → 70–77%, Riverside 31 → 40%.
  - Truth fix: Riverside-1 windows 5 → 7. The schedule says QNTY 1+2+1+1+2, and plan A1.1 shows seven window tags (E, E, C, B, B, D, A); 5 was the type count. Riverside-3 (truth 3 against a QNTY sum of 10) is probably the same mistake, but it is unchecked.
- **20 Nov, SK/MB assembly schedules (B's request):**
  - Cause: SK/MB print some rows as one span in the thickness column (`1 1/2"/38mm CONTINUOUS RIGID INSULATION`). The performance notes sit 9 pt left of the PERFORMANCE header, so they fell inside the table and out-numbered the real material column. And with no name column, the fallback looked for names at the header's x, where nothing sits.
  - Fix (`extract/assemblies.py`): a thickness cell that runs on into words also gives that row's material. The table stops COL_TOL short of the next header. With no name column, the name is the material column's first row, unless a multi-word name sits in the thickness column (NOR's garage), which keeps reading nothing rather than a wall cut off above its studs.
  - CMHC assemblies kept: 413 → 493. SK/MB 0–1 → 5–13 per set (W1, F1, F2, R1 and the P walls read in full). Also new: ATL_Fourplex_03 P1–P6, QC_ADU_01 P1, ATL_Fourplex_01 R3/R4, ATL_Sixplex W1 gains its cladding placeholder. No AB, BC or ON assembly moved; Alberta gate unchanged.
  - Still wrong: SK/MB F3+ blocks are cut by the tag midpoint (the known BC limitation), and SKMB_ADU_02's floor tables still read nothing.
- **23 Nov, US wall legends (A1 blockers 2 and 6):**
  - `extract/assemblies.legend_assemblies_on_page` reads `EXTERIOR - 5 1/2" WOOD STUD W/ PLYWOOD SHEATHING AND FINISH` / `INTERIOR - 3 1/2" WOOD STUD W/ ONE LAYER GYP. WALL BOARD` as assemblies W1 / P1, named "from the wall legend, untagged". It runs only where no schedule yields an assembly, on floor-plan and legend sheets.
  - Only the stud depth is stated, so only the studs are counted. Sheathing and gypsum are kept as layers with no thickness and each gets a warning; no standard thickness is filled in. Words from the neighbouring column are dropped unless they name a known material. "GYP." is spelled out in the legend reader only, so CMHC's own layers do not move.
  - The builder counts a legend assembly as referenced (US plans mark wall types by hatch, not tag). Its P depth also lets partitions be found.
  - Dev: assemblies read on 6 of 15 sets (was 0). Escondido 1–4 coverage 77/70/77/77 → 85/78/85/85%. Santa Cruz reads both walls but still has no footprint, so coverage does not move. Riverside has no wall legend in this form and still reads no assembly; its wall types are not yet surveyed.
- **24 Nov, A3 conventions (framing notes, inline datums, sheet numbers, titles) and Landmark scores:**
  - `extract/assemblies.stud_note_assemblies_on_page` reads `ALL EXTERIOR STUDS TO BE 2x6 @ 16" O.C.` (Riverside's structural notes) and AU/UK `EXTERIOR WALL STUDS SHALL BE 90x45 @ 600 CRS` as W1, studs only. Nominal 2x4/6/8/10/12 → 89/140/184/235/286 mm. It runs only where no schedule or legend gives an exterior wall. Nailing and trimmer notes are not wall specs.
  - `Layer.framing_share`: a stated spacing sets the stud share (38 mm / spacing, plus the plates' fixed 5.5%). Unstated or within 5% of 400 mm (16" is 406) keeps 0.15. Every CMHC framing layer states 406 mm, so none moved.
  - `extract/levels.inline_level`: a datum printed with its label in one span (`8'-0" PLATE HEIGHT`, `0'-0" FINISHED FLOOR`, `T.O. PLATE 9'-1 1/8"`, `FIN. FLR. EL. 100'-0"`, `FFL +3.000`, `FFL RL 12.450`, `OKFF ±0,00`). Only floor and plate labels count, so `TOP OF TRELLIS` / `TOP OF COLUMN` are not floors. Metric needs a datum code, so CMHC ladders are untouched.
  - `intake/classify`: ISO 19650 numbers (`PRJ-ORG-ZZ-00-DR-A-1001`, discipline from the role). The fallback title now prefers the title-block column, so Santa Cruz A2-101 types as FLOOR PLANS rather than a drawing heading "LEGEND".
  - **New refusal (`builder.gather`):** an outline whose sides disagree with its own dimension strings by more than 25% (`footprint.REFUSE_PCT`) is not used as the footprint; a WARNING gap names it. Every CMHC footprint agrees within 7.53%. Partitions still use such an outline as a page bound (refusing it there moved AB_Sixplex partitions).
  - Dev (rules only): Riverside 1–4 coverage 40 → 60%, storeys now right, height error 0.0 m, W1 read. Santa Cruz 2: the plan is now found and its 8.8 × 9.4 m outline (53% off its dimensions) refused, so no footprint, as before. Santa Cruz 3 is **worse**: 2 → 50% coverage, but on a footprint 40% short. The main plan's wall stroke splits in two, and the right half's 7.5 m matches a partial chain to 2.4%. This is the next footprint task (it is the Riverside class of "succeeds wrongly").
  - CMHC: `run_pipeline.py` coverage identical on all 53 sets (`out/after_legend.json` → `out/after_a3.json`), none below `out/baseline.json`. IFC footprint median 3.1%, 25/38 within 5%, unchanged. Alberta gate unchanged. 937 tests pass.
  - Landmark (rules only): RPL 13%, RSL 13%, Townhome 66% coverage; sheets typed 79/83/95%; a scale found on all three. None read an assembly schedule or openings schedule; RPL and RSL read no floor datum. These go in the A3 queue.
  - Not built: `3068` door codes (none in the dev or Landmark corpus), decimal comma, AU rebar `N12-300`. The AU sets state `1 : 100` but draw their dimensions as outlines (878 characters on a 13,509-path sheet), so they wait for vision.
- **24 Nov, part of a plan is not the footprint; Landmark wall heights:**
  - `geometry/footprint.detect_footprint` drops an outline when an overall dimension just outside one side covers that side and runs more than 1.25× past it (`OUTRUN_RATIO`). Santa Cruz 3's right half (one stroke; the living room is poched) matched a partial chain to 2.4% while `44'-0 1/4"` spans the whole. Its next candidate is 76% off its dimensions, so the builder refuses it: **no footprint, rather than one 40% short**. Coverage 50 → 2%, which is the honest number.
  - Two exemptions, each found by a CMHC test or the pipeline rather than reasoned: (1) a candidate within 15% of the stated per-storey area is the intended unit, since a rowhouse unit sits inside its block's dimension by design (AB_Rowhouse_02 otherwise swapped its 131 m² stated area for the 528 m² block, carbon 29.0 → 59.6 t). (2) Partitions call with `whole_building=False`: a setback upper storey is legitimately smaller than the floors below (QC_Rowhouse_02 A102 is 8.6 m deep under a 16.66 m overall, and lost 24 m of partitions).
  - CMHC: only ON_ADU_02 moves. It took the 5.0 × 7.0 m A100 (28.6% off the IFC) and now takes A101, 7.0 × 8.5 m, exact; carbon 13.0 → 18.0 t. IFC footprint median 3.1 → 2.6%, within 5% 25 → 26/38, within 10% 32 → 33, within 25% 33 → 34. Alberta gate unchanged.
  - `extract/levels.wall_heights_on_page`: Landmark's elevations label each storey `MAIN FLOOR WALL HEIGHT` / `SECOND FLOOR WALL HEIGHT` / `FLOOR THICKNESS` beside a feet-inches dimension, with no datum ladder. It runs only where no datum ladder reads. Floors stack as wall height plus the stated floor thickness. The top storey's stated height is used rather than copying the one below, and the net basis deducts one floor, not two. With two or more storeys and no thickness stated, nothing is built.
  - Landmark (rules only): RPL 13 → 48%, RSL 13 → 48%, Townhome 66% (unchanged, it has datums). Checked by hand against the elevations; no Landmark dimension is recorded here. Assemblies, openings and the foundation still read nothing on all three; that is the next Landmark task.
- **24 Nov, Alberta 9.36 energy tables (exterior wall):**
  - `extract/assemblies.energy_table_assemblies_on_page` reads the `MATERIAL | RSI` table that Alberta permit sets carry under each detail. Each row states its thickness in its name (`7/16" OSB SHEATHING`, `2X6 STUDS @ 24" O.C. W/ R22`, `5/8" DRYWALL`). A wrapped row carries its RSI on its last line, which is how rows are split. Air films are dropped. The title is the nearest lettering ≥1.6× the row size below TOTAL. The detail's own tag is kept, so the plans' tag counts still choose.
  - Only the house's exterior wall is used: a title containing EXTERIOR WALL(S), not GARAGE or TALL WALL. It runs only where no schedule or legend gives a W assembly. A stated 24" spacing sets the stud share, and the batt shares the stud cavity. The R-value stays in the name; the batt maps to CMHC's mineral-wool factor, as every CMHC batt does, so that factor is the catalogue's assumption, not the drawing's.
  - Landmark (rules only): RPL and RSL now read their exterior wall's full build-up; it was studs only. Coverage stays 48%, because the coverage score counts wall area, which was already there. CMHC and dev are identical on every set.
  - Not done: Townhome's tables (page rotated 90°, titles only 1.2× the rows, tags `EW1`/`EW2`), and the floor, roof and foundation tables on the same sheets.
  - Hygiene: the 24 Nov wall-height entry, its code comment and its tests had carried Landmark's own dimensions. They are replaced here with generic values. Commit `a62f98c` (message and diff) still holds them in history.
- **24 Nov, imperial foundations (A3 specs) and Landmark's basements:**
  - `extract/specs.py` reads strip footings in inches (`24"Wx10"H CONC. STRIP FOOTING`, `16" x 8" CONT. FTG`, `Footings · Minimum 20" x 10''`; pad footings refused), a foundation wall in inches (`10" WIDE CONC. FOUNDATION WALL`), a basement's stated wall height (`8'-6" FOUNDATION WALL HEIGHT`, new `FoundationSpec.foundation_wall_height_mm`), and slabs written `4'' (nominal) thick 25 MPA concrete slab`, `150 THK SLAB`, `SLAB ON GRADE, 100mm THICK`.
  - A set with no structural sheet at all (Landmark numbers none) reads its whole foundation from the other sheets; before, only the slab was taken from them.
  - `takeoff/framing.py` (B's, announced under Requests): a stated foundation wall height replaces frost depth + 200 mm. Screw piles beside strip footings with no grade beam (a deck) no longer make a "foundation is on screw piles" line.
  - Landmark (rules only): RPL 48 → 91%, RSL 48 → 91%, Townhome 66 → 91% coverage. Each now reads its footing section, foundation wall thickness and slab; RPL also its wall height. Still missing on all three: openings (sizes are stacked W/H labels at each opening, no schedule) and the floor/roof assemblies. No Landmark quantity is recorded here.
  - CMHC: `foundation_spec_for` gives identical specs on all 53 sets with and without this change, and no CMHC sheet states a foundation wall height. Alberta gate unchanged. `run_pipeline.py` coverage is at or above `out/baseline.json` on every set.
  - Dev (rules only, before this change): Escondido 78–85%, Riverside 85%, Santa Cruz 2–9%; the AU sets, Citrus Heights and the BC catalogue read 0% and need vision (outlined text or image only).
- **24 Nov, openings from plan size labels (Landmark):**
  - `extract/openings.size_labels_on_page`: with no schedule anywhere in the set, each opening's size is read from the width-over-height pair written at it on the plan (`3'-0"` over `6'-8"`), horizontal or turned with the wall. One plan per storey (`group_by_storey`), basement included. A pair 6'-5" or taller is a door. Lone dimensions, side-by-side chain labels and stacks outside 1'-20' x 1'-9' are not openings.
  - The window and door lines say the count comes from plan labels, cite imperial dimension text, and carry a WARNING gap: an opening drawn without its label is not counted, and interior and exterior doors are not told apart.
  - Landmark (rules only): coverage 91 -> 100% on all three. Counts checked by eye against the plans (the townhome row reads one garage door per unit); no Landmark quantity is recorded here.
  - CMHC: no set takes this path (every one has a schedule), so nothing moves. No dev set takes it either.
  - Not done: Landmark's floor and roof energy tables (they are rim joists, cantilevers and chases; their wrapped rows do not parse into thicknesses, and `framing.py` already estimates the main floor and roof framing).
- **24 Nov, upload speed (2.5x) and robustness:**
  - The scaled inventory (`inventory(with_scale=True)`) re-classified every page instead of reusing the cached plain inventory; it now adds the calibration on top of it. Every `get_text("dict")` in A's readers skips image blocks (`intake.spans.TEXT_DICT`); none read them, and decoding them was most of a page's read time.
  - Full takeoffs are byte-identical on 10 sets (AB, ON, SK/MB, QC, BC, NOR, ATL, Riverside, Escondido, Landmark RPL): 201 s -> 81 s in total under the same load; a typical CMHC set 11-38 s -> 5-8 s.
  - Odd uploads checked: blank pages, a text-only document, one image, rotated and 200-inch pages give no lines and an honest "no readable floor plan" gap. An empty, truncated, encrypted or non-PDF file is refused by the upload endpoint (415 / 422 with the reason), nothing stored.
- **24 Nov, A6 numbers for B (branch finals/reading at the upload speed-up):**
  - Full suite green. CMHC coverage against `out/baseline.json`: no set down; 52 sets, mean 67.6% -> 79.6% (ATL_Fourplex_01 40 -> 100, ATL_ADU_02 62 -> 100, BC_ADU_01 78 -> 85, ...). Alberta gate unchanged.
  - Dev split (score_blind, no vision): Escondido 78-85%, Riverside 85% (Riverside-4 footprint +37%, still open), Santa Cruz 2-9%. AU sets, Citrus Heights and the BC catalogue read 0% and need vision (outlined text, scans, a brochure).
  - Sponsor sets (metric, multi-file): every line produced, coverage 100%; quantities deliberately not recorded here.
  - Upload of a five-file set through the UI: about 5 s to a bill. Opening lines without a schedule now cite their plan sheet (`p9` when the sheet has no number) with detail `SIZE LABELS ON PLAN`; the missing-schedule notes now say what was read instead rather than "cannot be produced".
- **24 Nov, dev footprints:**
  - Santa Cruz 2 now has a footprint (8.77 x 7.75 m, 0.7% from its dimensions; it was refused at 53%). A grid-line stub drawn at the wall weight hung off the outline to its bubble; the outline less its free-ended runs is now offered alongside and the dimensions pick. On 211 plan pages (53 CMHC sets + dev) 7 change, and every CMHC takeoff that touches them is identical (3 stay refused, 1 moves 1 mm); Riverside 3 tightens to 0.1%.
  - Santa Cruz 3 is still refused, on purpose: its plan is drawn at a lighter weight than a whole-sheet group that wins and is refused, and letting the lighter one through gives 13.4 x 8.2 m against 13.4 x 7.3 (the heat-pump pad drawn beside the house). A 12% "measured" footprint is worse than the refusal; the outline trace covers it.
  - Riverside 4's +37% is not a misread: the outline is 12.21 x 9.47 m against 12.19 x 9.45. The building is an L and `Footprint.area_m2` is the bounding rectangle. A polygon area would fix it but moves the area on every non-rectangular CMHC set, the scored ones included; left for after the freeze.
- **24 Nov, US storey height from T.O.S.:** a dotted top-of-slab marker (`T.O.S.` / `T.O. SLAB`) is now a floor datum, so a one-storey US section with `PLATE 8'-1"` over `T.O.S. 0'-0"` gives its wall height. Santa Cruz 2 and 3: none -> 2.464 m (truth 2.464). No Alberta set carries the label; the QC and Escondido sets that do are identical.
- **24 Nov, sponsor sets end to end:** all three projects give a 22-line bill (2-12 s). The missing-schedule note no longer claims the wall was read from the drawings where the wall is the assumed standard. Partitions stay assumed on these sets: the linework measure needs a stated partition depth and has only been validated on Alberta's lineweights.
- **24 Nov, US opening schedules:** a header token with a digit is no longer a column (a "3.C" grid bubble beside Santa Cruz 3's window schedule became its tag column and lost every window), and a "WINDOW LEGEND" / "DOOR LEGEND" that heads a WIDTH / HEIGHT table counts when the page has no schedule of that kind (Escondido 2's window schedule is titled that way). Windows against truth: Santa Cruz 3 0 -> 11 (10, the 11th is an alternate), Escondido 2 0 -> 7 (7), Escondido 4 10 -> 11 (11). Openings compared on all 71 sets (CMHC, dev, sponsor): only those three change.
- **24 Nov, dev truth correction:** Riverside 3 `windows` 3 -> 8. A0.1's window schedule states QNTY A 5, B 2, C 1 (D x2 is an option in place of doors 3 and 4); 3 was the number of types. We read 10, counting the optional D; open_err for that set is now 2 rather than 7, and the change is to the reference, not the reader.
- **24 Nov, dev rerun after today's fixes** (`out/blind.json` dev rows): coverage Riverside 1–4 60 -> 85%, Escondido 2 78 -> 85%, Santa Cruz 2 9 -> 85% (footprint 14% off, height exact), Santa Cruz 3 2 -> 17% (height exact; footprint still refused on purpose). Opening error: Escondido 2 7 -> 0, Escondido 4 1 -> 0, Riverside 3 7 -> 2, Santa Cruz 3 13 -> 4. No set went down. AU, Citrus and the BC catalogue stay at 0% until vision runs.
