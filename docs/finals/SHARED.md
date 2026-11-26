# Finals: shared plan (read this first)

Submission is due **Fri 27 Nov**. The finals score four things: **product accuracy, tech robustness, UX, commercialization**. The judges' message:

- It must not work only on CMHC sets. It must read **any plan set from anywhere**: metric or imperial, any country's drafting conventions, vector or scanned.
- A real person must be able to use it **without training**.
- It must be easy to turn into a product.

Two people build this in parallel, each with their own Claude agent:

| Branch | Stream | Owner | Goal | Instructions |
|---|---|---|---|---|
| `finals/reading` | A | Divyesh | the tool can **read** any plan set | [READING.md](READING.md) |
| `finals/product` | B | Shiven | a person can **use and trust** it | [PRODUCT.md](PRODUCT.md) |

**Agent: run `git branch --show-current` and follow your stream's file. Only edit files your stream owns (table below).**

---

## START HERE (25 Nov, evening): UX session findings and the last 36 hours

**This section replaces the "what next" of everything below.** The earlier sections stay as the record.

### What the UX session asked for (25 Nov)

Practitioners liked the UI. They want every number **traceable, explicit and editable**: today "every number seems to come out of thin air", and if a builder is audited they must show where each figure came from. In priority order:

1. **Traceability (number one).** Every quantity and every kgCO₂e figure shows how it was calculated (quantity × conversion × factor), from which sheet and which source (EPD / database, version). It appears in the app *and* in the CSV.
2. **No unit ambiguity.** Carbon is always **kgCO₂e** (CO₂e as a subscript in the UI); mass is always **kg (mass)**; no number appears without its unit.
3. **Interactive plan set.** Click a highlighted element on the sheet (e.g. one interior partition) to include or exclude it; totals update.
4. **Edit everything.** Material, dimension (thickness, area, length) and quantity on every line, with the calculation re-shown live.
5. **Your own material swaps.** Pick any material, or type your own factor with its source.
6. **Builder material library.** Upload the builder's list of available materials (and their EPDs) with the plan set; swaps and edits are suggested from it.
7. **Canada only, for now.** Factors and method are location dependent: make Canada accurate. The US and Mexico are a later extension.

### Scope change (25 Nov): Canada only

This supersedes the North America section below.
- The US sets go to `split: out_of_scope` in `corpus/sources.yaml`.
- The US code stays, but it is not demoed or claimed. The US holdout score (taken once, 25 Nov) is a footnote only.

### Where we are (25 Nov)

**Accuracy**
- CMHC: median A1–A3 / BPR A1–A5 is **0.539** over 44 text-readable sets; **11** of those are within ±30%.
- By region: ON 0.72, BC 0.64, ATL 0.46, SKMB 0.37.
- NOR image-only sets read through vision.
- Alberta gate unchanged (AB_Fourplex_01 45,167 kg).

**Traceability today**
- The bill's "how this was derived" shows qty → converted × rate = kgCO₂e.
- The converted quantity, density and thickness used are **not stored**.
- Waste factors are loaded but **never applied**.
- The CSV lacks GWP value, declared unit, conversion, density, geography, data type, attribution and override note.

**Editing today**
- Quantity only.
- Swaps and open decisions are browser-only: not saved, not exported.
- The substitution delta uses the unconverted quantity (bug).

**Other gaps**
- The sheet view is not clickable; partitions are one line with no ID per wall.
- The upload is PDF only; there is no slot for supporting documents.
- About 12 places say plain "kg" meaning carbon, and about 15 numbers have no unit.

### New hand-offs (contracts)

- **C7. Per-wall partitions (A → B)**
  - `partitions_for(design)` returns each `PartitionRun` with `walls: list[Wall(id, rect, length_m, depth_mm)]`; `rects` stays.
  - IDs are stable across rebuilds: `p{page}-w{n}`, sorted by position.
  - The walls' lengths sum to `length_m`.
- **C8. Calculation record (B)**
  - `ecarbon/carbon/calc_trace.py` `explain(line, carbon_line, factor) -> CalcTrace(steps)`.
  - Each step carries a label, value, unit and source.
  - It reproduces `kg_co2e` exactly. The API, CSV and report read it; `models.py` is untouched.
- **C9. Line edits (B)**
  - `POST /projects/{id}/lines/{line_id}` takes `{quantity?, material?, factor_id?, thickness_mm?, excluded_walls?, note}`.
  - Edits are stored per workspace and replayed after every rebuild.
  - They are labelled `"stated: "` (C3).
- **C10. Material library (B, landed 25 Nov; A9 now only the optional EPD-PDF reading)**
  - `ecarbon/carbon/user_factors.py` `read_material_list(content, filename) -> (list[FactorRef], list[row_error])`, from CSV/XLSX in a template (`GET /materials/template.csv`).
  - Template columns: name, category, declared_unit, gwp_value, gwp_unit, density_kg_m3, source, epd_id, valid_to.
  - B turns each row into a project factor (`geography="user"`, `data_type="epd"`, source "Builder library: <file>").

### Schedule

| When | Stream A (Divyesh) | Stream B (Shiven) |
|---|---|---|
| Wed 25 night | A7 per-wall partitions (C7) | B9 calc trace: backend, CSV, report |
| Thu 26 am | A8 Canada accuracy: SK/MB, ATL | B9 UI calc popovers; B10 units |
| Thu 26 pm | A8: BC, ON, NOR; A9 material list (C10) | B11 edit everything; B12 own materials and library; B13 clickable partitions |
| Thu 26 eve | A10 hardening → **freeze 10 pm** | B14 Canadian factor sources and waste; accuracy refresh → **freeze** |
| Fri 27 | — | B15 deck, video, deploy, warm, **submit** |

**Cut list,** in order, if behind:
1. EPD PDF reading by vision (A9 optional)
2. exterior-wall and footprint toggles (B13 stretch)
3. provincial factor gap-fill (B14)
4. hero "how this adds up" breakdown
5. thickness editing

### New Canadian sets (25 Nov night): a real Canadian blind test

Ten non-CMHC Ontario sets are in `corpus/sources.yaml` and `~/ec-data/global/` (local only, never in git). Toronto's sets are made-in-Toronto designs, not the CMHC catalogue.

- **Dev, for A to tune on (6):** `ca-on-toronto-{gs,ls}-{studio,2bed}-0` (garden and laneway suites) and `ca-on-mississauga-gs-{studio,1bed}` (one PDF per sheet; read as a folder).
- **Holdout (4), A never opens:** `ca-on-toronto-{fourplex,sixplex}-{narrow,wide}`. B writes their answer key; they are scored once after the freeze.
- **Out of scope:** the `-1` suite variants, which are the same buildings plus one sheet.

What the rules read today on the dev sets: 4 of 6 read nothing and 2 give only an assumed foundation and roof.
- The Toronto suites have no sheet numbers in their title blocks, so classification falls back to content.
- The Mississauga files are one sheet each, and most aren't typed.
- **Who does what (changed 25 Nov night, Shiven's call):** the plan sets are on Shiven's machine, so **B does the reading fixes on these six dev sets**. The blind protocol still holds:
  - B wrote the holdout answer key first (`corpus/holdout_truth.yaml`, Canadian section, committed before any rule change);
  - B tunes only on the dev sets and does not open the four multiplexes again until scoring.
  - Before the key, B saw only one automatic run's summary of them (totals, line counts, element types), not the drawings' details.
  - The judges are told the same team wrote the key and the rules.
- A8 on CMHC accuracy stays with A.

`scripts/fetch_corpus.py --split dev` fetches the dev sets. If the Mississauga entries fail there, the sheets are listed on its publication pages.

### Done means (Thu evening, on Fly)

1. Upload a Canadian set plus a material CSV.
2. Click the total → a line's calculation → its sheet.
3. Exclude two partitions.
4. Swap insulation to a library material.
5. Export the CSV.
6. In a spreadsheet, the CSV's `calculation` column reproduces the app's total.

**Every PR:**
- full pytest with the catalogue (gate included)
- ruff
- the guard grep
- the CMHC matrix: 53/53 totals unchanged unless the PR says why

---

## Scope change (24 Nov): North America only

The team narrowed the finals claim to **North American plan sets** (Canada and
the US). The Australian and Irish sets in `corpus/sources.yaml` are now
`split: out_of_scope`: they stay on disk but are not scored, and A3's AU/UK/DE
conventions are dropped from the plan. The blind holdout is the 17 US sets.

The vision fallback is shown on **one or two demo sets only**, to keep API
spend down; its cache makes reruns free. The rules-only path is what every
set is scored on.

## Where we start (19 Nov, `main` at f32dd72)

- **AB_Fourplex_01:** 38,075 kgCO₂e, 34,659 without partitions, 124.4 kg/m².
- **How it reads:** rules for vector PDFs only, with no OCR, AI or HTTP client.
- **CMHC coverage:** median 52% across 52 packages. Alberta reads 100%; SK/MB and NOR read about 9%. The 8 NOR sets with no text layer read nothing.
- **Imperial is half-done.** These already parse feet and inches:
  - `geometry/scale.py`: `parse_imperial`, `parse_dimension`, `_SCALE_IMPERIAL_RE`
  - `extract/assemblies._parse_inches`
  - `extract/openings.parse_ft_in`

  These are metric only:
  - level elevations (`extract/levels.py` `_ELEV_RE`)
  - foundation specs (`extract/specs.py`)
  - the builder, which hard-codes `BasisSource.DIM_TEXT_METRIC`
  - every unit string in the UI
- **Factors:** all 20 in `carbon/seed_factors.json` are Canadian, and `find_by_material` ignores geography.
- **No manual fallback.** When reading fails, nothing accepts a user-stated scale, footprint or storey heights.
- **Never tested on a plan set from outside Canada.**

## Rules (both streams)

- **Small PRs into `main`, often.** When a task is green, PR it; after it merges, `git merge origin/main` into your branch. Before starting each task, `git merge origin/main`. No rebasing of pushed work, no force-push.
- **Every PR passes, before merge:**
  - `.venv/bin/python -m pytest`, *with the full catalogue* (the Alberta gate skips without it)
  - `.venv/bin/python -m ruff check ecarbon scripts tests deploy`
  - the guard grep from CLAUDE.md, which must print nothing
  - `scripts/run_pipeline.py`: CMHC coverage must not drop below `out/baseline.json`
- **Only Shiven's machine has the full catalogue,** so Shiven's agent runs the full suite on `finals/reading` PRs before they merge. Say so in the PR body.
- **The gate doesn't move silently.** If a pin in `tests/test_alberta_gate.py` moves, the commit message gives the before/after numbers and the reason.
- **`ecarbon/models.py` is frozen.** New labels go in fields that already exist: `Basis.note`, `assumptions`, `Provenance.bbox`, `BasisSource.USER`.
- **No plan set ever enters git:** CMHC, corpus or anything else. Corpus files live in `~/ec-data/global/`.
- **The project's point still holds:** measured, inferred and assumed are never blurred, and the tool says nothing rather than guess. A change that makes the tool quieter about its own uncertainty is the wrong change.
- **Feature freeze: Wed 25, end of day.** Thu 26 is judge feedback and submission material only.

## File ownership

| Area | Owner |
|---|---|
| `ecarbon/extract/*`, `ecarbon/geometry/*`, `ecarbon/intake/*` (incl. new `intake/locale.py`), new `ecarbon/vision/*` | **A reading** |
| `ecarbon/takeoff/builder.py`: `gather()`, extractor calls and line building | **A reading** |
| `ecarbon/takeoff/builder.py`: the three override hooks only (scale, footprint, heights; C2) | **B product** |
| new `ecarbon/takeoff/overrides.py` | **B product** |
| `ecarbon/carbon/*` (`seed_factors.json`, `store.py`, `calculate.py`) | **B product** |
| `ecarbon/api/main.py`, `ecarbon/report.py` | **B product** |
| `web/src/*` | **B product** |
| `scripts/score_blind.py`, `corpus/dev_truth.yaml`, `out/blind.json` (dev rows) | **A reading** |
| `scripts/accuracy.py`, `corpus/holdout_truth.yaml`, `ecarbon/bench/*`, `web/src/accuracy.json` | **B product** |
| `corpus/sources.yaml`, `scripts/fetch_corpus.py` | **B** maintains; **A** may add dev sets |
| `docs/finals/*`, `CLAUDE.md` | either; tick your own checklist, and announce other edits |

If you need a change in a file the other stream owns, write it under "Requests" at the bottom of this file, in the same PR, rather than editing the file.

## Hand-offs between streams (agreed contracts; build against them)

| ID | Contract | Owner | Status |
|---|---|---|---|
| C1 | `ecarbon/intake/locale.py`: `detect_locale(design) -> Locale` | A | ☑ stub ☑ real |
| C2 | `ecarbon/takeoff/overrides.py` `Overrides`, threaded through `gather()` / `build_takeoff()` | B | ☑ landed (B2) |
| C3 | Line labels: `"vision: "` and `"stated: "` note prefixes | A writes vision lines; B writes stated lines and renders both | ☑ A (`vision/validate.py`) ☐ B |
| C4 | Upload stage `"vision"` | A emits, B displays | ☑ A emits (`build_takeoff`) ☐ B displays |
| C5 | `locale` exposed by the API | B | ☐ |
| C6 | `out/blind.json` row schema | A writes dev rows, B the holdout | ☑ `score_set` + dev rows ☐ holdout |

**C1 Locale.**
```python
@dataclass(frozen=True)
class Locale:
    unit_system: Literal["metric", "imperial", "mixed"] | None
    country: str | None      # ISO 3166-1 alpha-2, e.g. "US", "CA", "AU", "GB", "IN"
    region: str | None       # e.g. "CA-AB", "US-CA", "AU-VIC"
    evidence: list[str]      # human-readable reasons, e.g. 'title block: "Boise, ID 83702"'
def detect_locale(design) -> Locale: ...
```
A lands a stub returning `Locale(None, None, None, [])` on day 1, then the real version. Callers must handle `None` everywhere.

**C2 Overrides.**
```python
@dataclass
class Overrides:
    scale_mm_per_pt: dict[int, float] = field(default_factory=dict)   # page index -> mm per PDF point
    footprint: tuple[int, list[tuple[float, float]]] | None = None     # (page, polygon in PDF points)
    storey_heights_m: list[float] | None = None
```
- Threaded as `gather(design, expected_area_m2=None, overrides=None)` and `build_takeoff(..., overrides=None)`.
- `None` means today's behaviour exactly.
- A must not restructure the scale, footprint or heights blocks in `gather()` without noting it under "Requests".

**C3 Labels.**
- **Vision-read values:**
  - `Confidence.INFERRED`
  - `Basis.note = "vision: <sheet_no>: '<verbatim quote>'"`
  - one `assumptions` entry naming the provider and model
  - `Provenance.bbox` set in PDF points
- **User-stated values:** `BasisSource.USER` in `basis.sources`, and `Basis.note = "stated: <what the user gave>"`.
- B's UI shows a "read by AI" chip or a "you said" chip from these prefixes. Keep the prefixes exact.

**C4 Upload stage.** A calls `progress("vision", "<n> sheets")` from `build_takeoff` when vision runs. B adds `"vision"` to `UPLOAD_STAGES` in `web/src/App.jsx`, shown only when the server reports it.

**C5 API.** B adds `locale: {unit_system, country, region, evidence}` to the project/massing response, from C1. It is used for the default display units and the factor region.

**C6 Bench rows (`out/blind.json`)** are a list of:
```json
{"set": "...", "split": "dev|holdout", "country": "US", "units": "imperial",
 "sheets_ok": 0.0, "scale_ok": true, "footprint_err_pct": 0.0, "storeys_ok": true,
 "heights_err_m": 0.0, "assemblies_found": 0, "openings_err": 0, "coverage_pct": 0.0,
 "vision_used": false, "broke": ["levels: no datum read", "..."]}
```
- `scripts/score_blind.py` exposes `score_set(design_dir, truth) -> dict`.
- B's `scripts/accuracy.py` imports it to score the holdout, so both splits are scored identically.

## Getting the plan sets (data repo)

All plan-set data the team may use is in the **private** repo `shivenlak/ecarbon-plansets` (ask Shiven for access):

```bash
git clone https://github.com/shivenlak/ecarbon-plansets.git ~/ec-data
```

- `~/ec-data/cmhc/` holds all 52 CMHC packages. That is `EC_DATA`'s default, so the full suite (Alberta gate included) stops skipping.
- `~/ec-data/global/` holds the **dev** corpus. `fetch_corpus.py --split dev` sees it as already present.
- `~/ec-data/landmark/` holds the confidential Landmark sets.
- **Holdout sets are deliberately not in that repo** (blind protocol below).
- Never copy anything from it into this repo. This repo is public, and the guard grep rejects `.pdf` and `landmark`.

## The global corpus and the blind protocol

- **Where things live:**
  - `corpus/sources.yaml` lists every outside plan set: URL, country, units, building type, licence and **split**.
  - `scripts/fetch_corpus.py [--split dev|holdout]` downloads them into `~/ec-data/global/<id>/`.
  - Files never enter git.
- **The blind protocol:**
  - **Stream A only ever fetches and opens `dev` sets.**
  - Stream B writes `corpus/holdout_truth.yaml` and runs the holdout scoring.
  - The reading engineer never tunes on the holdout, so "tested blind on sets we never saw" is literally true.
  - Holdout numbers are recorded once, after Wednesday's freeze, and quoted as they are.
- **Licences:** each set's licence is recorded in `sources.yaml`. Sets whose licence forbids redistribution are used for local testing only, never bundled into the deployed image.

## Landmark Homes sets (sponsor-provided, CONFIDENTIAL)

- **What arrived:** on 19 Nov the sponsor shared three Landmark projects, **RPL**, **RSL** and **Townhome**, "for calibration and testing". Next week it adds a **material list and high-level quantity takeoff** for each. Those takeoffs are the best ground truth we will ever get: a real builder's own quantities. Check that they've arrived before scoring.
- **What the sponsor scores:**
  1. drawing recognition across styles and housing types
  2. quantity takeoff accuracy
  3. UX for industry use
  4. implementation and commercialization
- **Confidentiality rules (stricter than the corpus):**
  - Files live in `~/ec-data/landmark/<project>/`.
  - They never go in git, `corpus/sources.yaml`, `deploy/data`, the image, the live site, screenshots in the repo, or the deck, unless the sponsor says so. The guard grep already matches `landmark` and `.pdf`.
  - Don't commit the Drive link or the file names either. Each person downloads from the shared folder themselves.
  - **Vision API calls on Landmark pages are allowed** (confirmed by the team, 19 Nov). Use providers' API tiers that don't train on submitted data, and keep the vision cache for these pages under `~/ec-data/landmark/`, not in the repo.
  - Quote results as aggregate accuracy (for example "within X% of Landmark's own takeoff"), never as their drawings or quantities.
- **How each set is delivered:** as **several PDFs per project**: Floor Layout, Roof Layout, Building Details, Schedule A, Final Blueprint, Foundation, and Mech & Electrical. That is how real builders deliver, and today both `config.pdf_designs()` and the upload treat each PDF as its own design. That gap is now a task on both streams: A4b and B2b.
- **Split:** all three are **calibration (dev)** for Stream A, as the sponsor intends. Stream B scores them against Landmark's takeoffs when those arrive (B6).

## Schedule

| Day | A reading (Divyesh) | B product (Shiven) |
|---|---|---|
| Thu 19 | A1 corpus (dev), dev truth; C1 stub | B1 holdout truth; start B2 |
| Fri 20 | A1 failure list; A2 locale (coaching pm) | B2 overrides and endpoints (C2 merged) |
| Sat–Sun 21–22 | A3 global rules; A4 vision tasks 1–3 | B3 guided UI; B4 factors |
| Mon 23 | A4 tasks 4–6; provider bake-off | B5 units toggle; **UX session** |
| Tue 24 | A5 image-only sets | B6 accuracy; **UX session 2:00–3:30** |
| Wed 25 | A6 hardening → **freeze at end of day** | UX fixes; holdout scored → **freeze** |
| Thu 26 | numbers for the deck; judge feedback | B8 flowchart, deck, video |
| Fri 27 | — | deploy, warm, **submit** |

**Cut list,** in order, if behind:
1. B3 corner-tracing mode (keep scale and heights)
2. A4 window and door schedule task
3. B5 export units
4. A3 bar scales

## Done means (Wed end-to-end check)

On localhost with vision on, upload a **holdout** set from each of at least 3 countries through the UI. Each should come out with:
- a bill
- correct display units
- region factors, or the stated Canadian fallback
- a trace on every line
- an honest list of anything it couldn't read

On the CMHC side: the gate passes and coverage is at or above baseline.

## Validation log (B checks A's branch on the full catalogue)

- **19 Nov, `finals/reading` @ bc9d259** (7 commits, not yet in a PR):
  - **Tests:** full suite **790 passed, 0 skipped** (Alberta gate included); ruff clean.
  - **Diff:** no Landmark content or files, and no change to the builder's C2 hooks.
  - **Landmark (rules only):** sheets classified **0% → 79–95%**, and a scale is now found on all three. Still **0 quantities** (no assemblies, slab or footing spec read), and Townhome reaches 20% coverage. Next blockers, in order: assembly schedule, foundation spec, openings.
  - **Dev corpus:** all 11 scored sets still produce no quantities. The top blockers are assemblies, slab thickness, levels and openings (11/11 each).
  - **Note:** `folder_design` writes its joined copy to `<set>/.ecarbon/`, inside the data repo. That repo now ignores `.ecarbon/` (pushed).
  - **OK to PR into `main`.**

## Requests (cross-stream asks; append, don't edit the other stream's files)

- **A → B (A4b hand-off for B2b):** `ecarbon.config.folder_design(folder: Path) -> Design` makes one design from every PDF in a folder. Save an upload's files together in one folder and call it.
  - The files are joined into `<folder>/.ecarbon/combined.pdf`, so page indices, trace and renders work unchanged.
  - `ecarbon.config.source_of(design.drawings_pdf, page) -> (file name, page in file) | None` maps a page back to its file, for the files list and provenance.
  - A folder holding a single PDF is that PDF, unchanged.
  - `pdf_designs()` skips the `.ecarbon/` copy.
- **B → A, 19 Nov: concrete is the largest measured shortfall (please look).** `scripts/accuracy.py` against the IFC models: concrete volume is a median **−57%** (0 of 21 designs within 10%). On AB_Fourplex_01 we have 33.9 m³ (slab 20.0 + grade beam 13.9) against the IFC's 77.5 m³ of `CMHC_Concrete, CIP`.
  - Candidates: foundation walls (never produced), the grade beam section or run, piers or pads, or the IFC counting something the drawings don't show.
  - Run `python scripts/accuracy.py AB_Fourplex_01` for the per-material table.
  - Per-design detail is local only, in `out/accuracy_cmhc.json`.
- **B → A, 19 Nov: FYI, joists and trusses are now estimated.** `takeoff/framing.py`, hooked once in `build_takeoff`, adds ASSUMED lines for the deferred F/R framing, each tracing to its schedule row. It adds +426 kg on Fourplex 01 (gate pins updated, with the reason). If a structural framing plan states member, depth or spacing, reading it should replace the standard.
- **B → A, 19 Nov: from a multi-file upload (B2b works).** When the footprint's sheet has no sheet number, the progress line prints "off sheet None"; say the page instead. On one confidential multi-file set the measured footprint looks large for its type, so it's worth checking against the plan locally (details are not for this public repo).
- **B → A, 19 Nov: I touched two of your extractors, narrowly, for accuracy.** Please merge `origin/main` before editing them.
  - **`extract/levels.py`:** `ELEV_DY_MAX` 16 → 24 pt (SK/MB prints the datum 21 pt under its label); `_ELEV_RE` accepts a whole-metre "0 m"; `T/O CONCRETE` / `T/O SLAB` count as the ground datum. All 5 multi-storey SK/MB sets now read 3 × 2.744 m. Every set that read before is unchanged.
  - **`extract/specs.py`:** three tight slab patterns (`4" [100mm] SLAB`, `100mm [4"] THICK SLAB`, `SLAB ON GRADE 100mm`), range 75–250 mm, with load-table entries refused by the trailing colon. A slab read off a foundation the drawings call generic goes to `spec.generic_slab_mm`, never `slab_thickness_mm`.
- **B → A: SK/MB assembly schedules parse wrong (your area; worth the most after vision).** A001 states layers as `5/8"/16mm   TYPE 'X' GYPSUM BOARD` and `3 1/2"/89mm   WOOD STUD FRAMING @406mm O/C`, imperial and metric joined by a slash. `assemblies_on_page` picks the notes column as the layers ("NOTE: ADD ACOUSTIC…"). Fixing it unlocks floors, roof and wall layers for all 7 SK/MB sets, currently 5% of CMHC's figure.
- **B → A: framing plans state the real joists and trusses on some sets.** SK/MB S101/S102: "560 TJI 302 DEEP @ 305 O.C.", "PRE-ENGINEERED SCISSOR TRUSSES @ 610 O.C.". `takeoff/framing.py` uses a 400 mm standard; reading these would make the joist lines stated rather than assumed. I can take it if you don't.
- **DONE by B, 23 Nov (with Shiven's OK, as A had not started; please review):** fixes 1–3 below landed in `vision/validate.py` (a text layer with no digit is checked as an image), `vision/__init__.render` (downscales to fit 10 MB) and `builder._vision_candidates` (Task.SHEET on unclassified pages, typed by `sheet_type_of`). The vision notes now say when a quote came from an image rather than claiming it was located in text. NOR_Fourplex_Municipal went from 0 lines to 14 (footprint 11.973 × 17.986 m).
- **B → A, 23 Nov: vision on NOR is right, but `validate.py` throws it away (top priority before the freeze).** I ran `ECARBON_VISION=claude` (Opus 5.5) on NOR_Fourplex_Municipal as a scratch probe, without editing your files.
  - **Results:** the SHEET task classified all 37 pages correctly (A100 main floor plan, A101 second floor, sections). FOOTPRINT on A100 answered `11973` × `17986` (the IFC bbox is 11.97 × 17.97 m). LEVELS on the sections answered `T/O ROOF 8.444 m` (the IFC height is 8.45 m).
  - **Fix 1, `validate._check`:** the page carries a 33-character stamp, so `spans` is non-empty, `locate()` fails, and every answer is dropped. The dimensions are outlined linework, not text (17,719 drawings, 33 text chars). Please treat a page whose text layer is too thin to hold its own dimensions (e.g. no span parses as a dimension/elevation, or fewer than ~200 chars) the same as a raster page: keep the reading, INFERRED, with `RASTER_NOTE`.
  - **Fix 2, builder vision trigger:** it only tries sheets the rules classified as `PLAN_TYPES`, and on NOR none are classified, so `vision_sheets` stays 0. Please run Task.SHEET on unclassified pages first (37 pages took 94 s, a few cents), then FOOTPRINT on the plans and LEVELS on the sections.
  - **Fix 3, `ClaudeProvider.read`:** one NOR page at 110 DPI is a 14.2 MB PNG, over the API's 10 MB image limit (400). Downscale, or JPEG, before sending.
  - **Provider:** use Claude for CMHC and Landmark. Our Gemini key is free tier (Pro quota 0), and the free tier may use inputs to improve Google's products. The Claude API does not train on inputs.
- **A → B, 23 Nov: C1 is real, so `carbon/region.detect` now gets answers.** `detect_locale` names a region only from a state or province seen on 2+ sheets; all US dev sets give `US-CA`, CMHC sets their province (ATL and image-only NOR give none, so the typed jurisdiction still applies). Two things in your code worth a look: (1) a title-block region now outranks the typed jurisdiction even when they agree on the country; (2) `from_text`'s bare `, OR` rule fires on ordinary text ("US-OR" on 1 sheet of most ATL/QC sets, 5 sheets of Riverside); the 2-sheet rule absorbs it on our side. The result is cached per file, so calling it from both the builder and the upload costs one read.
- **DONE by B, 24 Nov (with Shiven's OK; please review, all small and pinned by tests):** edits in A's files, found by a per-element gap matrix against CMHC's LCA.
  - `extract/openings.py`: an imperial-only window schedule (BC, `3' - 0"` × `6' - 0"`, no mm column) now gives width *and* height. All 7 BC sets had lost their windows.
  - `extract/assemblies.thickness_in_name`: a layer with an empty thickness cell takes a depth its description opens with (`11 1/4" UNFACED FIBERGLASS BATT`); spacings (`16" O.C.`, `@`) are refused.
  - `extract/specs.py`: `FROST_WALL_RE` (ATL's drawn `8" FROST WALL DETAIL` / `FROST WALL, SEE DETAIL` means a strip footing plus a frost wall of that thickness; the plural concrete-strength note does not count); `STRIP AND PAD FOOTING` (ON); `FOOTINGS AT 1200mm BELOW GRADE` as the frost depth; `THICKENED EDGE SLAB` as its own system (SK/MB).
  - `extract/levels.repair_level_span`: the scoped 0x1D glyph-shift repair, like `repair_schedule_cell`, accepted only when it yields a capitalised level label or an elevation that parses. ON's `T/O F/F THIRD` was refused by the global repair, so four ON multiplexes read 2 storeys instead of 3. Only five sets' ladders change (four ON, ATL_Fourplex_01 Option 2); Alberta is unchanged.
- **DONE by A, 24 Nov, in B's `takeoff/framing.py` and the screw-pile line in `builder._foundation_lines` (please review, both small):**
  - `framing.py` foundation wall: a stated `foundation_wall_height_mm` (new `FoundationSpec` field, read from `8'-6" FOUNDATION WALL HEIGHT`-style notes) replaces frost depth + 200 mm, and the "a frost wall is assumed, not a basement" caveat is dropped when it is stated. Landmark's basements were priced as frost walls, about half their height.
  - Screw piles beside strip footings with no grade beam carry a deck or porch, so `ln-screw-piles` ("Foundation is on screw piles") is no longer emitted for `system == "strip_footing"`; the "0 mm dia" text is gone when no diameter is stated.
- **A → B, 24 Nov: status of your asks to A.**
  - *"off sheet None"*: fixed; the upload progress line and the vision footprint assumption now name the page (`p11`) on an unnumbered sheet. The `Provenance.sheet_no=inputs.footprint_sheet` uses in your `framing.py` still pass `None` there, which is the honest value; your call whether the UI labels it.
  - *SK/MB slash schedules*: done; SKMB_ADU_01 reads W1, F1, P1, P2, R1 with layer thicknesses.
  - *C3 / C4 / C6*: A's halves are in (ticked above).
  - *Joists and trusses off S101/S102* (`TJI 302 DEEP @ 305`, `SCISSOR TRUSSES @ 610`): not started on our side. Take it if you have room; otherwise A picks it up after the freeze-day fixes.
  - *Concrete shortfall*: stated foundation wall heights now replace frost depth + 200 (see "DONE by A" above); piers, pads and the IFC comparison are not re-run.
- **A → B, 25 Nov (night): the title block no longer calls 37 CMHC sets Ontario. Read this before B14.** Every SK/MB, QC, NOR, ON and ATL set came out `CA-ON`, "from the title block". The cause was CMHC's own head office ("700 Montreal Road, Ottawa, Ontario"), the licence's "laws of the Province of Ontario", and `from_text` being handed whole pages, where an assembly tag shaped like a postcode ("P1A 2X4") made "slab **on** grade" read as Ontario.
  - Now `intake/locale.py` skips those two clauses and gives `from_text` one line at a time. Those sets read `CA` with no province; BC_Sixplex is still `CA-BC`; the global corpus is unchanged.
  - Totals don't move today, because no factor in the store is `CA-ON`. With provincial factors (B14), though, every CMHC set would have been priced as Ontario. The drawings rarely name the province, so the upload's jurisdiction is the better source. Today `region.detect` (your file) returns the title block's bare `CA` before it looks at the jurisdiction; letting a jurisdiction's province win over a bare country is a one-line change there.
- **A → B, 25 Nov (night): C7 is in, so B13 can start.** `partitions_for(design).runs[i].walls` is a list of `Wall(id, rect, length_m, depth_mm)` (import `Wall` from `ecarbon.geometry.partitions`).
  - `id` is `p{page}-w{n}`, numbered top to bottom, then left to right; it is the same on every rebuild of the same PDF.
  - `rect` is in unrotated page points, the same space as `rects`, which is unchanged. Every rect in `rects` is exactly one wall's `rect`.
  - `depth_mm` is the stated partition depth the wall matched. Wall lengths sum to the run's `length_m` within 0.01 m (each is rounded to 1 mm).
  - To exclude walls: subtract their `length_m` from the run. In `_partition_lines` (`takeoff/builder.py`), area is length × (wall height ÷ storeys), and volume uses the *mean* stated depth, not each wall's. Watch out: if the measured area falls below 15% of the floor-area estimate, the line switches to the assumed estimate, so excluding most walls can make the total go *up*.
- **A → B, 25 Nov (overnight): what A is doing, so we don't double up.** Divyesh OK'd: API spend up to $2.50, run the full suite and fix failures, then **deploy and warm** if it is green. Shiven: please don't deploy overnight; if you need to, say so here first.
  - **Scanned-set demo, no key on the server:** `ECARBON_VISION=cache` replays saved Claude answers and never calls the API. The Dockerfile sets it, points `ECARBON_VISION_CACHE` at `/data/cmhc/_vision`, and pins `pymupdf==2.1`, because the answers are keyed by the rendered page. `deploy/stage_data.py` adds NOR_Fourplex_Municipal to the default selection. `deploy/prebuild.py` run with `ECARBON_VISION_SEED=~/.cache/ecarbon/vision` copies into the image only the answers those sets use (38). The first run cost $0.90; footprint 11.97 × 17.95 m, height 8.444 m.
  - **Vision honesty fixes in the builder:** "No readable floor plan / section" now says the footprint or heights were read by AI from the image of A100 / A300 (WARNING, not BLOCKING). The exterior wall cites A300, not "vision".
  - **Then:** full suite → fix → PR #46 → deploy + `deploy/warm.sh`. After that: the concrete shortfall (piers, pads, the IFC comparison), then maybe one more scanned set within the $2.50.
  - **Not touching:** joists and trusses off S101/S102 (yours if you want them), anything in `web/src`, `api/main.py`, `carbon/*`.
- **A → B, 25 Nov: please fix in `api/main.py` `get_massing` (your file).** The model note always says "{w} x {d} m measured from the linework, … storeys from the section datums". On a vision footprint (`inputs.vision` non-empty) it should say "read by AI from the image of {inputs.footprint_sheet}", and for heights the same when `inputs.vision_levels` is set. NOR_Fourplex_Municipal shows it today.
- **A → B, 25 Nov (afternoon): the live site gains NOR_ADU_Municipal** (a second scanned set, 8,493 kgCO2e, single storey). It needs the 10 new saved answers that are only in Divyesh's `deploy/data/_vision` (49 now), so the deploy has to come from Divyesh's machine, or Divyesh sends you that folder. `deploy/stage_data.py` already selects it.
- **A → B, 25 Nov (day): when you redeploy, take `main` after the vision box fix lands.** It moves NOR's trace highlight onto the dimension it was read from (it pointed at the wrong spot before). Code only: `deploy/data/_vision` and the prebuild steps are unchanged. Also new: a vision cross-check note on a rules footprint, which never fires on the live site (cache mode has no saved answers for those pages).
- **A → B, 25 Nov (morning): where the overnight run ended. Shiven, one ask: the deploy.**
  - Done and pushed on `finals/reading` (PR #46): merged `main` (#48, #49); full suite green on the merge (Alberta gate 39/39); ruff clean. Conflicts resolved so both sides keep their cases: your value-first datum reader runs after A's `inline_level`, your `assumed_frost_mm` sits under A's stated wall height, your `locale.py` taken whole. `mark_units` now reuses `inputs.locale` instead of reading the PDF again.
  - Vision: Citrus Heights (dev) went from nothing to its exact 31'-0" x 16'-0" footprint (a licence stamp no longer counts as checkable text; the footprint prompt stops at the wall, not over a porch). NOR re-read to the same 215 m2. Total spend $1.71 of the $2.50.
  - **Not deployed: the `ecarbon` Fly app is in your Fly account and Divyesh's login cannot see it.** Either add Divyesh to the org (`fly orgs invite`), or deploy it yourself after merging #46: `deploy/stage_data.py` (now includes NOR_Fourplex_Municipal), then the prebuild line it prints, then `fly deploy --remote-only --ha=false` and `deploy/warm.sh`. The prebuild needs the 39 saved vision answers. They are not in git (CMHC-derived) and live in Divyesh's `deploy/data/_vision`, so the simplest route is that Divyesh deploys once added. Without them the image still builds and NOR honestly reads nothing.
  - Checked locally against the staged image data with no key: NOR shows the 11.97 x 17.97 m two-storey model, 34,178 kgCO2e, every line tagged "read by AI"; the AB sets as before. Your `get_massing` note ask above still applies.
- **DONE by B, 24 Nov (scope change, please review):** `intake/locale.py` is now real for North America (US vs Canada by address, ZIP/postcode and building-code citations; units by dimension strings; None on a weak or split vote). Country is right on every CMHC and US set it answers; region is wrong on most ATL sets (reads CA-ON), harmless for factors and frost depth but worth a look. `extract/levels.py` reads a value-first datum span ("8'-0\" PLATE HEIGHT", "0'-0\" FINISHED FLOOR"), floor and plate labels only, so the four Riverside dev sets read 1 storey at 2.438 m instead of none.
- **DONE by B, 25 Nov (demo set, dev split; please review):** `intake/classify.py`: in the wide title-block search, text running the same way as the boilerplate beside the number comes first, so Santa Cruz's vertical "FLOOR PLANS" and "EXTERIOR ELEVATIONS & BUILDING SECTIONS" titles beat nearer horizontal "LEGEND"/"KEYNOTES" panel headings (`Span.vertical`, new). `extract/levels.py`: "T.O.S." counts as a floor only at the 0 datum (top of slab; elsewhere it can be top of steel). us-santacruz-adu-2 went from 2 lines (openings only) to a full bill, width within 0.1%, plate 2.464 m as stated; its depth still includes the porch (9.41 vs 7.70 m).
- **DONE by B, 25 Nov (B's files, FYI A):** a drawn wall or partition type that yields only its stud layer (the US wall legends since #46: "2x6 studs") now gets the standard build-up's other layers (sheathing, cavity fill, gypsum) as ASSUMED lines beside the drawn studs (`framing.missing_layer_lines`); before, they went uncounted. The 3D footing is drawn at the bill's foundation depth (`Massing.foundation_depth_m`) instead of a fixed 1.2 m Alberta grade beam. Holdout scored once, rules only: `out/blind_holdout.json`, summary in `web/src/accuracy.json`.
- **A → B, 26 Nov: A8 first batch (FYI, plus two things that touch you).**
  - **Your `set_partitions` API now scales a *mix*.** `_partition_lines` splits the measured run across the P-types by floor-plan tag count (`_partition_mix`; AB_Fourplex_01 P1/P2/P3/P5 70/17/8/6%, partition carbon against the IFC −43% → −15%, median over 7 AB sets 37% → 15%). Excluding walls still subtracts from the run, but every type now shrinks by the same share, whichever type the excluded wall was. If B13 needs per-type exclusion, `PartitionRun.walls[].depth_mm` is the hook; say if you want it.
  - **Gate moved, proof in commit c9b8b8e:** 45167 → 46880 (all of it the partition split; the partition-free 41751 pin is unchanged). `test_api` n_lines 24 → 37 for the same reason.
  - **The 0.65 target is mostly scope, not reading.** Pricing the IFC itself at our factors gives a median **0.41** of BPR A1–A5 (45 sets), while our reading sits at **0.91** of the IFC on the same materials. QC_Fourplex_01 reads 42 m³ of concrete against the IFC's 40 m³, yet BPR puts 66 t in its foundations. The rest of the gap is A4/A5, rebar and BPR's factors, which the drawings don't state. Worth a line in the deck rather than a fudge factor.

### A → B, 26 Nov: report accuracy against both references (user's decision)

The user wants the submission to show two accuracy figures side by side:
- **vs IFC model (reading):** our A1–A3 against the IFC's own quantities priced at our factors. This is what the tool controls. Median 0.91 (`carbon.ours_same_materials_kg` / `carbon.ifc_at_our_factors_kg` in `out/accuracy_cmhc.json`).
- **vs CMHC BPR (full scope):** the headline the brief asks for (`carbon.ratio_to_a1_a5`), now a median of 0.58. One line should explain the gap: BPR adds A4/A5, rebar and its own factors that the drawings don't state. Pricing the IFC itself reaches only 0.41 of BPR.

Both fields are already in every row. Nothing new is needed from A.

### A → B, 26 Nov: party walls are their own class now

Demising walls (a schedule name with DEMISING or PARTY: AB/BC/ON/SKMB P tags, ATL W6/W7) are priced as `element_class: "party_wall"`. Their line IDs keep the `ln-interior-partition-` prefix, because their area is a share of the same measured or assumed partition run, so "total without partitions" still drops them. Totals are unchanged except ATL, where W6/W7 were not priced before.
- **Ask:** add `party_wall: "Party walls"` to `CLASS_LABEL` in web/src/App.jsx. It currently falls back to "Party Wall". `scripts/accuracy.py` already maps it to interiors.

### A → B, 26 Nov: a CMU factor, please

ON_Fourplex_01's N1 foundation states `190 CONCRETE MASONRY UNITS`, but the store has no masonry factor, so `ln-foundation-wall` prices an assumed 200 mm solid cast-in-place wall. That overstates a hollow-core block wall. **Ask:** a `CMHC_Concrete Masonry Unit` (or generic CMU per m³ or m²) factor in `carbon/seed_factors.json`. A will then read the N1 CMU layer into the foundation line. Until then the line will say what it stands in for.

### A → B, 26 Nov: a measured foundation wall height is not "stated"

QC labels T/O FOOTING on its elevations with no elevation printed. `gather()` now measures it off the datum ladder (`extract/levels.footing_on_ladder`: -2.44 m on QC, the IFC's figure) and sets `spec.foundation_wall_height_mm`, adding `"<sheet>: T/O FOOTING drawn at -2.44 m on the datum ladder"` to `spec.sources`. `framing.py`'s wall note then says "the stated foundation wall height (2439 mm)". The line's assumptions already say "measured, not printed", but the basis note should say so too, e.g. by checking `inputs.ladder_footing` (a new `TakeoffInputs` field). QC_Sixplex: wall 17.3 -> 29.7 m3, total 87.5 -> 90.9 t.

### A → B, 26 Nov: before/after numbers for the deck (A10)

All 53 CMHC sets, rules only (vision off), `scripts/run_pipeline.py` against `out/baseline.json` (23 Nov):

| | baseline (23 Nov) | now (2f95fed) |
|---|---|---|
| crashed | 0 | 0 |
| sets producing quantities | 45 | 45 (the 8 image-only NOR sets report why) |
| element coverage, median | 83.0% | **100%** |
| element coverage, mean | 67.6% | **82.4%** |
| sets below baseline coverage | – | **none** |
| seconds per design, median | 23.8 | 7.2 |

Accuracy, 44 sets with a BPR figure (`scripts/accuracy.py`; r1 = 25 Nov, r6 = d96e97a):

| | r1 | r6 |
|---|---|---|
| A1–A3 / BPR A1–A5, median | 0.566 | **0.608** |
| within ±30% | 11 | **15** |
| complete A1–A5 / BPR (your figure) | – | **0.776, 20 of 44** |
| ours / IFC on the same materials, median | 0.79 | **0.96** |

- The IFC priced at our factors is a median 0.41 of BPR. So the gap to BPR is scope the drawings don't state (A4/A5, rebar, BPR's factors), not reading. Use "0.96 of the IFC" for reading accuracy and the complete figure for BPR.
- NOR, image-only, by vision from the cached answers: all 8 sets give a bill at 0.13–0.43 of BPR, every line ASSUMED or INFERRED from an image. $1.51 spent in total; it is not in the 44.
- Toronto dev sets (non-CMHC, fetched today): 4 of 6 on disk. Coverage 76/76/0/91%; their build-ups and foundation callouts are not text (outlined), so assemblies read 0 by rules. A vision build-up task would be the next step, not done before the freeze.
