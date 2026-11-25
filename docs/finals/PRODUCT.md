# Stream B: `finals/product`. "Anyone can use it and trust it"

Owner: **Shiven**. Read [SHARED.md](SHARED.md) first: the rules, file ownership, contracts C1–C6, and the blind protocol all apply.

**Goal:** a builder or sustainability lead with no training uploads any plan set and gets the following:
- a number in their own units
- factors for their region
- a clear way to fix anything the tool couldn't read
- proof of how accurate it is

Plus the submission: deck, flowchart, video and a live deploy.

**You own:**
- `ecarbon/takeoff/overrides.py` (new) and the three override hooks in `gather()`
- `ecarbon/carbon/*`, `ecarbon/api/main.py`, `ecarbon/report.py`
- `web/src/*`
- `ecarbon/bench/*`, `scripts/accuracy.py`, `corpus/holdout_truth.yaml`, `corpus/sources.yaml`, `scripts/fetch_corpus.py`

**You also:** run the full suite with the catalogue on every `finals/reading` PR before it merges, since only this machine has all 52 CMHC sets.

Tick each box in the PR that lands it.

---

## B1. Holdout truth and licences (Thu 19)

- [ ] Run `python scripts/fetch_corpus.py --split holdout`.
- [x] Write `corpus/holdout_truth.yaml` (24 Nov: all 19 sets) in the same format as `dev_truth.yaml` (see READING.md A1). **Never share holdout sets with Stream A.**
- [ ] Confirm every `licence` row in `sources.yaml`. Anything that can't be redistributed is marked `local_only: true` and never goes in `deploy/data`.

## B2. Overrides plumbing (C2) and endpoints (Thu 19 – Fri 20; C2 merged by Fri)

- [x] **`ecarbon/takeoff/overrides.py`:** the `Overrides` dataclass from SHARED.md C2.
- [x] **Hooks in `gather()`.** These are the only builder edits B makes:
  - **Scale:** where the footprint loop calls `calibrate(page)`, `overrides.scale_mm_per_pt[page]` makes a trusted `ScaleEstimate`, with a note that it was stated by the user.
  - **Footprint:** `overrides.footprint` makes a `Footprint` from the polygon (PDF points × mm_per_pt), labelled as stated.
  - **Heights:** `overrides.storey_heights_m` replaces `storey_heights_for(...)` and clears the `STOREY_HEIGHT_UNKNOWN` gap.
  - Lines built from stated inputs get `BasisSource.USER` in `basis.sources` and a `"stated: ..."` note (C3).
  - `build_takeoff(..., overrides=None)` passes it through. `None` means today's behaviour exactly.
- [x] **`GET /projects/{id}/pages/{n}.png?dpi=`:** an owner-checked render of any page via `trace.render_page`. The existing trace image endpoint 404s for pages outside a line's trace.
- [x] **`POST /projects/{id}/calibrate`.** The body is one of:
  - `{"page": n, "p1": [x,y], "p2": [x,y], "length": "23'-6\"" | 7160}`: a known dimension, which sets `scale_mm_per_pt[n]`. Lengths parse with `scale.parse_dimension`, so feet and inches work.
  - `{"page": n, "corners": [[x,y], ...]}`: the footprint, in PDF points.
  - `{"storey_heights_m": [3.0, 2.8]}`, which also accepts feet strings.
  - `{"clear": true}`

  It stores the values on the workspace's fork (`_own`, so visitors stay private), rebuilds with `build_takeoff(design, facts, overrides=...)`, recomputes carbon, and returns the carbon result plus the new gaps.
- [x] Tests for each mode, plus: no overrides means identical totals.
- [x] Tick C2 in SHARED.md.

## B2b. Upload several PDFs as one project (by Tue 24; needs A4b)

Real builders, Landmark included, send a folder of PDFs: floor layout, roof, foundation, details, schedule.

- [x] **Upload dialog** (`App.jsx` `Upload`): accept several files, or a dropped folder. Show the files list, with the sheet types once they're read.
- [x] **`POST /projects/upload`:** take several `file` parts, save them together, and build one design with A4b's `folder_design()`. Keep the size limit across the whole set (raise it if needed), and check the `%PDF-` header on each file.
- [x] **Progress stages** count across files ("sheets: 23 across 6 files").
- [x] **Confidentiality:** test with the Landmark sets **on localhost only**. Never on the live site, and never in screenshots that get committed.

## B3. "Help it read this", the guided fallback UI (Sat 21 – Sun 22)

- [x] **Entry point.** Review notes with code `SCALE_NOT_FOUND`, a missing footprint (`GEOMETRY_AMBIGUOUS` / no footprint) or `STOREY_HEIGHT_UNKNOWN` get a **Help it read this** button. So does the upload result, when the bill came back thin.
- [x] **The viewer.** *(Built as `web/src/HelpRead.jsx` with its own pan/zoom rather than reusing `SheetView`, whose viewBox animation fights click placement. Deep link: `?help=scale|outline|heights`.)* Reuse `SheetView` (`web/src/App.jsx`, the SVG viewer behind the trace). Its viewBox is in PDF points, so a click converts to page coordinates with `svg.getScreenCTM().inverse()`. The image comes from B2's `pages/{n}.png`.
- [x] **Three modes**, each one screen, each showing what it will change:
  1. **Set the scale:** "Click both ends of a dimension you can read, then type it." It accepts `7160`, `7.16 m` or `23'-6"`.
  2. **Trace the building:** "Click each outside corner, then press Done."
  3. **Storey heights:** one box per storey, in metres or feet.
- [x] **Live result.** On save, call `/calibrate`; the 3D model, total and bill update. Lines show a **"you said"** chip (from the `"stated: "` prefix), and an **Undo** sends `{"clear": true}`.
- [x] Also render a **"read by AI"** chip for `"vision: "` lines (C3), with the quote in the hover.
- [x] **Copy:** plain verbs, sentence case, and each control says what happens. "Set scale", not "Submit".
- [x] Build, serve, screenshot and open the PNGs (CLAUDE.md): desktop, plus phones at 390 and 360 px with no horizontal overflow (reuse `scratchpad/drv/phone.js`-style checks).

## B4. Carbon factors by region (Sat 21 – Mon 23)

- [x] **New rows in `ecarbon/carbon/seed_factors.json`** *(19 Nov: 4 US rows, each read off its EPD: NRMCA V4 4000-00 330.17 and 4000-40FA 239.26 kg/m3, valid to 2031; AWC/CWC N. American lumber 63.12 kg/m3; GA 5/8" Type X 277 kg per 92.9 m2. The last two **expired** (2025-07 and 2026-04), are recorded as such and carry wider uncertainty. Still to do: US insulation, sheathing, windows and roofing; UK (ICE); AU.)* with `geography` set, each with `source`, `source_id`, `attribution`, `valid_from` and `uncertainty_pct`, like the existing rows:
  - **US (`geography: "US"`):** North American industry-average EPDs for ready-mix concrete (NRMCA), softwood lumber and OSB/plywood (AWC/APA), gypsum board (Gypsum Association), insulation (NAIMA), asphalt shingles (ARMA) and steel. Verify each value and its declared unit from the EPD itself; don't copy from memory.
  - **UK/EU (`GB` / `EU`):** the ICE database, after checking its licence and attribution terms.
  - **AU:** only if a public source with a clear licence exists. Otherwise no rows; the fallback note covers it.
- [x] **`store.find_by_material(name, geography=None)`:** with a geography, try an exact region match, then the same country, then today's lookup. **With `None` it must behave exactly as today.**
- [x] **When it falls back,** the carbon line gets a note: "No <country> factor for <material>; the Canadian factor is used." The range widens per the existing uncertainty.
- [x] **Thread the geography through:** `calculate_carbon(takeoff, provider, geography=None)` (`carbon/calculate.py`), from `Project.recompute`. The region comes from C1 locale, unless the upload form's jurisdiction says otherwise.
- [x] **UI:** "Factors: United States (from the title block) · change", with a small picker.
- [ ] Test that the CMHC totals are bit-identical (the gate proves it). Test the fallback note.

## B5. Metric / imperial toggle (Mon 23)

- [x] **One formatter.** `fmtQty(value, unit, system)` and `fmtIntensity(kgPerM2, system)` in `web/src/App.jsx`, next to `int` / `dec` / `UNIT_LABEL` / `prose`, exported for `Showcase.jsx`.
  - Conversions: m → ft, m² → ft², m³ → yd³. kg CO₂e is unchanged.
  - Intensity is kg CO₂e/m² or kg CO₂e/ft².
- [x] **Replace the hard-coded unit strings** (search `m²`, `m2`, `m³`, `kg/m`, `" m"` in `App.jsx` and `Showcase.jsx`). `prose()` must also convert numbers inside server sentences, or leave them in SI and label them so.
- [x] **Where it lives and remembers:** the toggle sits in the top bar, defaulting to `locale.unit_system` (C5; `mixed` → metric). The choice is remembered in `localStorage`, wrapped in try/catch.
- [ ] **Exports:** CSV and report get a units option. SI stays the default for CSV, so tools that import it don't break.
- [x] **C5:** *(served as `GET /projects/{id}/region` instead: geography + where it came from, including C1's title-block locale once real. The units default follows it: US → feet.)*

## B6. Accuracy you can demonstrate (Mon 23 – Wed 25)

- [x] **`scripts/accuracy.py`** writes `web/src/accuracy.json` (numbers only, no drawing content) from:
  - **CMHC against the IFC models:** per-element error for footprint (`bench/ifc_truth.building_bbox`), exterior wall area, slab volume and roof area (`bench/ifc_quantities.model_quantities`). Report the median and spread per element, and per region.
  - **Coverage before → after:** `out/baseline.json` vs `run_pipeline.py --json` now.
  - **Dev corpus:** `out/blind.json` from Stream A.
  - **Holdout:** score each holdout set with Stream A's `score_set` against `holdout_truth.yaml`. Run it once after the freeze and record it as-is.
  - **Landmark** (once the sponsor's material lists and takeoffs arrive): compare our quantities line by line with Landmark's own, for each of RPL, RSL and Townhome. This is the strongest evidence for the "quantity takeoff accuracy" criterion. Publish only **aggregate** errors (e.g. "walls within X% across three Landmark projects"), never their quantities or drawings. Keep the per-line comparison in `~/ec-data/landmark/`, not in the repo.
- [x] **Against professional assessments.** This answers the semi-final judges' first question: "how have you validated accuracy against a traditional professional assessment?"
  - **CMHC Building Performance Reports** are CMHC's own professional LCA for every design (73 reports, parsed by `ecarbon/bench/bpr.py`). Their scope is A1–A5, B4–B5, C2–C4, so **never compare totals directly**. Report:
    - (a) **element shares**: our % by element vs theirs (foundations, walls, roofs, floors…) across every scoreable design, with the spread
    - (b) **the bounds check**: our A1–A3 is below their total in every design, and the ratio sits in a plausible band (the IStructE guide puts A1–A3 at roughly half of A1–C4)
  - **Split the error into its two causes, because that's how a professional reviewer thinks:**
    - *quantity error:* against the IFC models and against Landmark's own takeoffs
    - *factor error:* run one design's quantities through **BEAM** (free; used by practitioners), compare per element, and record the BEAM version
  - Put a one-line, honest claim at the top of the panel and the deck. For example: "quantities within X% of the builder's own takeoff; carbon within Y% of BEAM on the same quantities; element shares track CMHC's professional reports to within Z points". Use only numbers we have actually measured.
- [x] **"How accurate is it" panel** in the app (a glass sheet like the others):
  - the CMHC error table
  - countries and unit systems tested
  - holdout results, labelled "blind"
  - a plain "doesn't cover yet" list (basements and foundation walls, joists and trusses, steel studs)
- [ ] **Docs:** update `docs/benchmark.md` and `docs/FINALS.md` with the new figures.

## B7. UX sessions (Mon 23 Building Codes, Tue 24 Embodied Carbon 2:00–3:30)

- [ ] **Prepare:** two holdout PDFs (one imperial), the localhost or live link, and a one-page script.
- [ ] **The test:** "here's a plan set, find its embodied carbon." Then say nothing, and write down every hesitation and wrong click.
- [ ] **Ask:**
  - Which export would you actually use: BEAM, One Click LCA, EC3, or CSV?
  - What would make you trust this number?
  - Who in your company would pay for it?
- [ ] Fix the top 3 issues Wed morning, and write the findings into `docs/FINALS.md` (they feed the commercialization slide).

## B8. Submission (Thu 26 – Fri 27)

- [ ] **`docs/ARCHITECTURE.md`:** a Mermaid flowchart of how the code works, exported to PNG for the form:
  ```
  upload → inventory/classify → locale → rules extractors → vision fallback (only where rules failed)
  → "help it read this" (only where both failed) → takeoff (measured / inferred / assumed, traced)
  → factors by region → carbon + range → UI / trace / exports
  ```
  Each box names its module.
- [ ] **Answer the semi-final judges' two questions head-on, one slide each, rehearsed at Friday's business coaching session:**
  1. **Accuracy:** the validation from B6, with the error split into quantity and factor, and what it doesn't cover yet.
  2. **Revenue model:**
     - the named paying customer (a production builder like Landmark, comparing variants before they build)
     - who else pays (LCA consultants and energy advisors using it to speed up their own work, and permit reviewers where embodied carbon reporting is required; verify each requirement before citing it)
     - pricing (per plan set plus an annual subscription, per `docs/business_plan.md`), with the unit economics
     - the pilot: Landmark through Edmonton Unlimited's Venture Pilots
     - Say plainly that it *speeds up* the professional assessment rather than replacing it. That makes it an accuracy answer and a sales answer at the same time.
- [ ] **Deck:** product and implementation plan, using the final numbers, the blind results, the provider bake-off and the UX findings. Fold in the judge feedback (Thu).
- [ ] **2-minute video:** upload a non-Canadian set live → the bill builds → toggle imperial → trace a line to its sheet → fix one thing with "Help it read this" → the accuracy panel.
- [ ] **Deploy:**
  - `EC_DATA="$PWD/deploy/data" .venv/bin/python deploy/prebuild.py`
  - `fly secrets set` for the vision key
  - `fly machine update d8de467a622dd8 --app ecarbon --autostart=true --yes`
  - `fly deploy --remote-only --ha=false`
  - `deploy/warm.sh`
  - Confirm the platform link and guest login.

---

## Findings (append as you go)

- *(UX session notes, holdout results, factor sources used)*
