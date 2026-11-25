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
| C1 | `ecarbon/intake/locale.py`: `detect_locale(design) -> Locale` | A | ☑ stub ☐ real |
| C2 | `ecarbon/takeoff/overrides.py` `Overrides`, threaded through `gather()` / `build_takeoff()` | B | ☑ landed (B2) |
| C3 | Line labels: `"vision: "` and `"stated: "` note prefixes | A writes vision lines; B writes stated lines and renders both | ☐ |
| C4 | Upload stage `"vision"` | A emits, B displays | ☐ |
| C5 | `locale` exposed by the API | B | ☐ |
| C6 | `out/blind.json` row schema | A writes dev rows, B the holdout | ☐ |

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
- **DONE by B, 24 Nov (with Shiven's OK; please review, all small and pinned by tests):** edits in A's files, found by a per-element gap matrix against CMHC's LCA.
  - `extract/openings.py`: an imperial-only window schedule (BC, `3' - 0"` × `6' - 0"`, no mm column) now gives width *and* height. All 7 BC sets had lost their windows.
  - `extract/assemblies.thickness_in_name`: a layer with an empty thickness cell takes a depth its description opens with (`11 1/4" UNFACED FIBERGLASS BATT`); spacings (`16" O.C.`, `@`) are refused.
  - `extract/specs.py`: `FROST_WALL_RE` (ATL's drawn `8" FROST WALL DETAIL` / `FROST WALL, SEE DETAIL` means a strip footing plus a frost wall of that thickness; the plural concrete-strength note does not count); `STRIP AND PAD FOOTING` (ON); `FOOTINGS AT 1200mm BELOW GRADE` as the frost depth; `THICKENED EDGE SLAB` as its own system (SK/MB).
  - `extract/levels.repair_level_span`: the scoped 0x1D glyph-shift repair, like `repair_schedule_cell`, accepted only when it yields a capitalised level label or an elevation that parses. ON's `T/O F/F THIRD` was refused by the global repair, so four ON multiplexes read 2 storeys instead of 3. Only five sets' ladders change (four ON, ATL_Fourplex_01 Option 2); Alberta is unchanged.
- **DONE by B, 24 Nov (scope change, please review):** `intake/locale.py` is now real for North America (US vs Canada by address, ZIP/postcode and building-code citations; units by dimension strings; None on a weak or split vote). Country is right on every CMHC and US set it answers; region is wrong on most ATL sets (reads CA-ON), harmless for factors and frost depth but worth a look. `extract/levels.py` reads a value-first datum span ("8'-0\" PLATE HEIGHT", "0'-0\" FINISHED FLOOR"), floor and plate labels only, so the four Riverside dev sets read 1 storey at 2.438 m instead of none.
