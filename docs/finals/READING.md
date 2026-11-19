# Stream A: `finals/reading`. "Reads any plan set, anywhere"

Owner: **Divyesh**. Read [SHARED.md](SHARED.md) first: the rules, file ownership, contracts C1–C6, and the blind protocol all apply.

**Goal:** a plan set from any country, drawn in any convention, metric or imperial, vector or scanned, comes out with a bill. Where the tool can't read something, it says so rather than guess.

**You own:** `ecarbon/extract/*`, `ecarbon/geometry/*`, `ecarbon/intake/*`, `ecarbon/vision/*` (new), `gather()` and line building in `ecarbon/takeoff/builder.py`, `scripts/score_blind.py`, `corpus/dev_truth.yaml`.

**You never open holdout sets.** Fetch with `--split dev` only.

Tick each box in the PR that lands it.

---

## A1. Corpus, scoring, failure list (Thu 19 – Fri 20)

- [ ] `python scripts/fetch_corpus.py --split dev` fetches into `~/ec-data/global/`.
- [ ] **Dev truth.** Write `corpus/dev_truth.yaml`, one entry per dev set, about 15 minutes each, read by eye off the drawings:
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
- [ ] **`scripts/score_blind.py`**:
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
- [ ] **C1 stub.** `ecarbon/intake/locale.py` with the `Locale` dataclass and `detect_locale()` returning all-`None`. PR it on day 1 so B can build against it. Tick C1 "stub" in SHARED.md.
- [ ] **Baseline.** Run `scripts/run_pipeline.py` on CMHC and save `out/baseline.json`. If `--json` doesn't exist yet, add a minimal one: per design, coverage % and total. This is the "must not regress" line.
- [ ] **Failure list.** Rank the `broke` strings across dev sets by how many sets each one blocks. Paste the top 10 into this file under "Findings". That list orders A3.

## A2. `intake/locale.py`, the real version (Fri 20)

- [ ] **Unit system:**
  - Vote across dimension labels using `DimLabel.unit_system` (`geometry/scale.py`, collected by `calibrate()`), plus the style of scale notes (`1:100` vs `1/4" = 1'-0"`).
  - Return `"metric"`, `"imperial"` or `"mixed"` (dual-dimensioned, as CMHC sets are), with counts in `evidence`.
- [ ] **Country and region** from the title-block and cover-sheet text. Use the same span reading as the rest of the code (`intake/spans.read_spans`).

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
- [ ] **Wire it in:**
  - `build_takeoff` calls `detect_locale` once.
  - The `BasisSource.DIM_TEXT_METRIC` hard-codes in `builder.py` become `DIM_TEXT_IMPERIAL` where the set is imperial.
  - Add an info gap when imperial: "drawn in feet and inches; quantities converted to SI".
  - CMHC sets are `mixed` and must keep their sources and totals.
- [ ] Unit tests: one per pattern, plus a CMHC set reading `CA` / `mixed`. Tick C1 "real".

## A3. Rules for global drafting conventions (Sat 21 – Sun 22)

Work in the order of the A1 failure list. Each new pattern gets a unit test, and **the Alberta gate must not move**.

- [ ] **`extract/levels.py`:**
  - feet elevations: `T.O. PLATE 9'-1 1/8"`, `TOP OF PLATE EL. 109'-1"`, `FIN. FLR. EL. 100'-0"`
  - relative datums such as `100'-0"` taken as ±0
  - AU `RL 12.450` (reduced levels)
  - UK `FFL +3.000` / `SSL` / `TOS`
  - DE `OKFF ±0,00`
  - Reuse `scale.parse_imperial`. Keep the plate-vs-ridge distinction (`roof_level_m`).
- [ ] **`extract/specs.py`:** `4" CONC. SLAB ON GRADE`, `16" x 8" CONT. FTG`, `#4 @ 12" O.C.`, `N12-300` (AU rebar), `150 THK SLAB`, `100mm thick`.
- [ ] **`extract/assemblies.py`:**
  - Nominal lumber: 2x4 → 89, 2x6 → 140, 2x8 → 184, 2x10 → 235, 2x12 → 286 mm. Also AU/UK `90x45` / `140x45` (stud depth is the first number).
  - Framing fraction from the stated spacing: `@ 16" O.C.` / `@ 24" O.C.` / `@ 400 crs` / `@ 600 crs`. Use the spacing to compute stud share instead of always `FRAMING_FRACTION = 0.15`; the no-spacing case keeps 0.15, so CMHC is unchanged.
  - Decimal comma (`2,40`).
  - US wall-type legends that are a list of notes rather than a layer table.
- [ ] **`extract/openings.py`:** imperial as primary when there's no metric column; `3068` / `2868` / `2668` door codes (W×H in feet-inches); tags `W-1`, `W01`, `D1`, `101A`.
- [ ] **`intake/classify.py`:**
  - US `A-101`, `A2.1`, `S-1`, `G-001`
  - UK BS 1192 / ISO 19650 numbering (`PRJ-XX-ZZ-DR-A-1001`)
  - AU `DA-01` / `CC-101`
  - titles such as "BUILDING SECTIONS", "WALL SECTIONS", "WALL TYPES", "DOOR & WINDOW SCHEDULE", "GENERAL ARRANGEMENT", "GROUND FLOOR PLAN", "FIRST FLOOR PLAN" (= the second storey in UK/AU usage!)
- [ ] **`geometry/scale.py`:** `1:100 @ A1`, `1:100 @A3`, `SCALE: 1/8" = 1'-0"` spacing variants, `NTS` as "no scale". Graphic bar scales only if cheap.
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
- [ ] **`vision/providers.py`:**
  - One interface: `read(png: bytes, task: Task) -> dict | None`.
  - Two adapters: `ClaudeProvider` and `GeminiProvider`. **Load the `claude-api` skill before writing the Claude adapter**, and use the current model ID and its structured-output/tool-use pattern.
  - Selected by `ECARBON_VISION=claude|gemini`, with keys from `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Unset means vision is off and behaviour is exactly as today.
  - Add the SDKs as an optional extra in `pyproject.toml` (`[project.optional-dependencies] vision = [...]`), imported lazily.
- [ ] **`vision/tasks.py`:** one pydantic answer schema plus a prompt per task, in priority order:
  1. sheet type and number
  2. scale note
  3. overall footprint dimensions (from dimension strings, not by measuring pixels)
  4. level datums / storey heights
  5. wall-type / assembly schedule
  6. window and door schedule

  Every field carries `quote` (the verbatim text it was read from) and `box` (pixel bbox). Every schema allows `found: false`, and the prompt says plainly that "not on this sheet" is the right answer when it isn't there.
- [ ] **`vision/validate.py`, quote-and-locate:**
  - Convert the box from pixels to PDF points (render DPI and page rotation; see how `trace.render_page` renders).
  - **Vector pages:** the quote, normalised, must be found in the page's own text (`read_spans`) within or near the box. Otherwise the answer is **dropped** and the drop logged.
  - **Raster pages:** there's no text to check, so the value is kept but capped at `INFERRED`, with the note "read from an image; not verifiable against text".
  - Numbers in the answer must parse out of the quote with the existing parsers (`parse_dimension`, `parse_scale_text`, `parse_imperial`). The model's own arithmetic is never trusted.
- [ ] **`vision/cache.py`:** a disk cache in `~/.cache/ecarbon/vision/` keyed by `sha256(png + task + PROMPT_VERSION + provider/model)`, plus a page budget per upload (env `ECARBON_VISION_MAX_PAGES`, default 12).
- [ ] **Into the takeoff:**
  - Results fill `TakeoffInputs` (scale → `ScaleEstimate`, footprint → `Footprint`, levels → `StoreyHeights`, schedules → `Assembly` / `Opening`), so line building is unchanged.
  - Labels per **C3**: `"vision: "` note, an `assumptions` entry, and `Provenance.bbox`. The trace highlight then works by itself, because `trace_line` honours `bbox` first.
  - Emit `progress("vision", ...)` (**C4**).
- [ ] **Cross-check:** where the rules and vision both answer, agreement goes in the note ("agrees with the dimension chain"), and disagreement becomes a WARNING `Gap` with both values. Never silently resolved.
- [ ] **Tests:** recorded provider responses under `tests/fixtures/vision/`. CI never calls an API. Test that the validator drops a hallucinated quote, and that vision-off leaves CMHC totals bit-identical.
- [ ] **Provider bake-off (Mon 23):**
  - Run both providers on every dev set.
  - Per provider, record: answers accepted by the validator, answers right against `dev_truth.yaml`, wrong answers that got through, answers dropped by the validator, $ per set, and seconds per set.
  - Choose the default by **accepted-and-right per dollar**. Put the table under "Findings"; it goes in the deck.

## A4b. Plan sets delivered as several PDFs (Landmark), by Mon 23

Landmark delivers each project as separate PDFs: Floor Layout, Roof Layout, Building Details, Schedule A, Final Blueprint, Foundation, and Mech & Electrical. See SHARED.md "Landmark Homes sets" for the **confidentiality rules**: vision is allowed, but nothing goes in git.

- [ ] **One design from a folder.** `config.pdf_designs(folder)` (or a new `folder_design`) makes **one** `Design` from all the PDFs in a folder, so the inventory sees every sheet across every file. Pages need a stable global index, plus a `(file, page)` mapping for provenance and trace. Check how `Design.drawings_pdf` is used (`config.py:44`, `intake/inventory.py`, `trace.render_page`), and keep single-PDF behaviour unchanged.
- [ ] **Sheet classification across files.** File names are a strong hint ("Foundation.pdf", "Roof Layout.pdf"). Use them only when the title block is unreadable, and record that as the basis.
- [ ] **Skip trades we don't count.** Mechanical/electrical sheets are recognised and skipped, with an info note.
- [ ] **Score the Landmark sets** with `score_blind.py` (rules only), using `~/ec-data/landmark/` as a dev source. Put the "what broke" items into the A3 queue. Scores go in Findings without any Landmark quantities quoted.
- [ ] **Hand-off for B2b:** tell B the function to call, e.g. `folder_design(path) -> Design`, under Requests in SHARED.md.

## A5. Image-only sets (Tue 24)

- [ ] Run vision on the 8 NOR CMHC sets with no text, and on any image-only sets in the dev corpus. **Target:** "nothing read" becomes a bill with every line `INFERRED` and traced. Record before/after.
- [ ] Make sure these sets still say plainly that the values were read from an image.

## A6. Hardening and numbers (Wed 25, freeze at end of day)

- [ ] Rerun `score_blind.py --split dev` and `run_pipeline.py --json`. Fix the top regressions. CMHC coverage must be at or above `out/baseline.json`.
- [ ] Hand B the numbers (under "Findings"): CMHC coverage before → after, dev stage scores before → after, the bake-off table, and NOR before → after.
- [ ] Freeze. After this, bug fixes only.

---

## Findings (append as you go)

- *(A1 failure list, A3 before/after, A4 bake-off, A5 NOR before/after)*
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
