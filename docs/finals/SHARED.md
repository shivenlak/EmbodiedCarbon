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
