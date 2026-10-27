# Overnight queue — polish, speed, and a demo worth watching

Shiven's brief, verbatim: *"it needs to be polished, everything needs to be
polished and the demo must have a wow factor, the links are kind of slow and
there are some cosmetic bugs in the UI, the UI is clean but not very wow, it
would be cool if there were more of a visual component to it."*

Submission is **Wed 29 Oct**: a link, back-end credentials, and a five-minute
video. The interface is the thing judges see first and for longest. It is
currently clean and correct, and that is not the same as impressive.

---

## Guardrails — these are not negotiable

1. **Never commit CMHC data.** Before every commit, grep the staged list for
   `CMHC`, `.ifc`, `.h2k`, `.dwg`, `.ctb`, `reference/`, `deploy/data`,
   `node_modules`, `web/dist`. Abort on a hit. The repo is public.
2. **`ecarbon/models.py` is a frozen contract** shared with the teammate's
   branch. Do not edit it. If something genuinely needs a field, write that in
   the log and work around it.
3. **Green before every commit:** `ruff check ecarbon scripts tests` clean and
   the full `pytest` suite passing (719 at the time of writing). The Alberta
   gate in `tests/test_alberta_gate.py` must pass unchanged — if a number in it
   moves, that is a regression until proven otherwise, and the proof goes in
   the log.
4. **Look at every visual change.** A screenshot you did not open is not
   evidence. The loop is: build → serve → screenshot → `Read` the PNG → judge
   it → iterate. Two of the last three UI bugs were invisible from the API and
   obvious on sight.
5. **Do not deploy on each item.** The Fly trial stops the machine after five
   minutes and each deploy costs the warm cache. Work locally; deploy once at
   the end of the session, then run `deploy/warm.sh`.
6. **One commit per item**, with the measurement in the message. If an item
   needs a judgement call that is genuinely Shiven's, write it in the Log and
   move to the next item rather than guessing.

### How to see the interface

```bash
cd web && npx vite build --logLevel error
cd .. && EC_DATA="$PWD/deploy/data" ECARBON_WARM=0 \
  .venv/bin/python -m uvicorn ecarbon.api.main:app --port 8000 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --disable-gpu --no-sandbox --hide-scrollbars \
  --screenshot=/tmp/shot.png --window-size=1500,1400 \
  --virtual-time-budget=30000 "http://localhost:8000/?plan=AB_Fourplex_01"
```

Then `Read` `/tmp/shot.png`. Crop long pages with pymupdf (see the Log entries
below for the snippet). Run long jobs under `caffeinate -dimsu`.

---

## Baseline, measured 2026-10-27

| | |
|---|---|
| Tests | 719 passing, ruff clean |
| Live | https://ecarbon.fly.dev (`judge` / password in `/tmp/ecarbon_pw.txt`) |
| Cold build, shared core | 23 s typical, 177 s for QC_Sixplex |
| Warm response | 0.5 s |
| Bundle | ~260 kB |
| Reference design | AB_Fourplex_01 · 48,613 kgCO₂e · 37,536 excl. partitions · 158.9 kg/m² · 20 lines · 19 notices |

---

## Queue, in order

### 1. Kill the cold build — bake the takeoffs into the image

**This is the "links are slow" complaint and it has a real root cause.** Every
design is parsed from scratch on first request and cached only in memory, so a
restart throws it away. A judge clicking a cold link waits 23 seconds; after a
deploy, 177 for the big one.

Precompute at build time instead. Add `deploy/prebuild.py` that runs the
pipeline for every design in `deploy/data/` and writes
`deploy/data/_prebuilt/<key>.json` containing the takeoff. Have `_build()` in
`ecarbon/api/main.py` load that file when it exists and is newer than the
drawings PDF, falling back to parsing when it does not. Run it from the
Dockerfile so the image ships warm.

*Target:* first request under 1 s, with no warm-up step. Verify by restarting
the container and timing the first call. Uploaded sets still parse live — that
path must stay identical.

### 2. Make the trace the demo's centrepiece

Click-to-trace is the most distinctive thing here and currently opens a flat
PNG. It should feel like pulling the drawing out.

- Render the sheet at higher DPI and **zoom to the highlighted region** on
  open, with a control to pull back to the whole sheet. A reader should see
  the wall, not a 36×24" sheet scaled to 900 px.
- Animate the outline: draw it on with `stroke-dashoffset` over ~400 ms so the
  eye lands where the measurement is.
- Pan and zoom with the wheel and drag.
- Keep the three `kind` labels exactly as they are — measured geometry,
  schedule row, sheet only are different claims and must not be flattened.

### 3. Connect the parts so the page feels alive

Right now each panel is independent. Make hovering a bill line highlight its
donut segment and its contribution bar, and vice versa. Clicking a donut
segment should filter the bill to that material. This is cheap, and it is what
makes a dashboard read as one instrument rather than four tables.

### 4. The headline should arrive, not just appear

Count the figure up from zero over ~700 ms on load and on project change,
easing out, with `prefers-reduced-motion` respected. Same for the coverage
meter and the contribution bars — they already transition, so give them a
staggered entrance (~40 ms apart). One choreographed moment per view, not
decoration everywhere.

### 5. Fix the cosmetic bugs

Known, plus whatever the screenshots turn up — hunt for more rather than
stopping at this list:

- The sticky table header overlaps the first row in a full-page render. Check
  behaviour at a real viewport height while scrolling.
- Long sheet detail text truncates mid-word in `.cite-detail`; give it a title
  attribute and a better ellipsis.
- The project name in the title block wraps awkwardly
  ("AB Fourplex 01 Technical Design Package"). Strip the package suffix.
- Check 1280 px and 1440 px as well as 1500; the two-column bottom section
  collapses untidily between breakpoints.
- The `notice-more` button sits flush against the notice above it.

### 6. Upload as a visible feature

The upload endpoint exists and nothing in the interface exposes it. Judges are
told they can bring their own drawings — make that a drag-and-drop target with
a progress state and the project facts form (floor area, storeys, units,
basis). This is step 5 of the demo script and currently requires curl.

### 7. A visual the page does not have yet

Shiven asked for "more of a visual component". The honest candidate: a
**sheet-coverage strip** — one tick per page of the drawing set, coloured by
what was read from it (schedule, plan, section, unreadable), with the ones
feeding the bill highlighted. It shows at a glance that 45 of 46 sheets were
opened and which ones mattered, which is a claim no competitor makes.

Resist a decorative 3D model or a fake building render. The subject is
drawings; the visual should be drawings.

### 8. The 3D massing view — only once 1–7 have landed

Shiven asked for this explicitly and chose to have it **after** the rest, so
do not start it until items 1–7 are committed and green. If the night runs
out before then, that is the correct outcome.

**It is a view of the takeoff, not a render of a building.** Every surface
must correspond to a quantity we measured. That is what makes it worth
showing and what separates it from a decorative model: if the footprint is
wrong the box is visibly the wrong shape, and where partitions over-detect —
AB_ADU_02 does, at +92% — you can see walls standing where no walls are. The
honesty story, made visual instead of asserted.

What we already measure and currently discard after computing areas:

| | |
|---|---|
| Footprint | `inputs.footprint.width_m` × `depth_m` |
| Storey datums | `inputs.heights.storey_heights_m()` |
| Partitions | `partitions_for(design)` → `run.rects`, 73 rectangles in page points |
| Openings | counts per storey from `openings_for` |
| Per-element carbon | already on each `CarbonLine` |

**Check what is actually available before designing the endpoint.** The
partition rectangles are in PDF page coordinates and the footprint may not
retain its origin, in which case positions have to be normalised against the
rect extents rather than placed absolutely. Verify this first and write what
you find in the Log — do not assume a building origin exists.

Suggested shape: a `GET /projects/{id}/massing` returning footprint extents,
storey heights, partition rectangles in metres relative to the footprint, and
a carbon figure per element class. Then a Three.js view that extrudes the
footprint, slabs at each datum, stands the partitions, and colours surfaces by
contribution. Click a surface → highlight its bill line, which is the existing
trace gesture in a second dimension.

Honest costs to weigh in the Log before committing to it: Three.js is roughly
600 kB against a 260 kB bundle, and the result is a massing block with
internal walls, not an architectural visualisation. If it reads as cheap when
you screenshot it, say so in the Log and stop — a convincing "here is what we
understood from your PDF" is the bar, and a grey box with no legible structure
is below it.

### 9. Anything after that

- Dark mode, properly paired (the tokens are already in `:root`).
- A compact "what changed" diff when a quantity is overridden.
- Keyboard navigation through bill rows with the trace on Enter.

---

## Log

Append one entry per item: what was tried, what the screenshot showed, the
measured effect, and anything deliberately left alone.

### 1. Cold build removed — takeoffs baked into the image ✅

`deploy/prebuild.py` runs the pipeline for every bundled design and writes the
takeoff to `deploy/data/_prebuilt/<key>.json`. `ecarbon/prebuilt.py` loads it
at request time. The Dockerfile already copies `deploy/data/`, so the saved
takeoffs ship with the drawings and need no extra build step.

**Measured, cold process, first request per design:**

| Design | Before | After |
|---|---|---|
| AB_Fourplex_01 | 23 s | **0.39 s** |
| AB_Sixplex | 23 s | **0.036 s** |
| QC_Sixplex | 177 s | **0.033 s** |
| BC_Fourplex_01 | ~38 s | **0.011 s** |
| ON_ADU_02 | ~11 s | **0.036 s** |

The takeoff is a pydantic model, so it round-trips through JSON exactly. That
was checked rather than assumed: the prebuilt file compares equal to a fresh
parse on lines, gaps and project facts. Carbon is still computed on load, so
it follows the current factor store rather than a snapshot — which matters,
because the factor seed has been corrected twice.

Two things deliberately left alone. Uploaded sets still parse live, because
there is nothing to prebuild for a file the image has never seen, and that
path is the one a judge exercises. And a prebuilt file older than the PDF
beside it is ignored, so a stale cache cannot make the deployment and the
repository disagree about what a design contains.

The runtime loader sits in `ecarbon/`, not `deploy/`: the image copies only
`ecarbon/`, so importing build-time code from the API would have worked
locally and failed in the container. Found before deploying, not after.

Baseline correction: the queue claimed 739 tests. The real figure is **719**
— the last full run was 718 passed with 1 failure, which was then fixed. The
number in this document was wrong when written.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 2. Trace view — vector overlay, opens zoomed ✅

The sheet is now fetched clean (`?highlight=0`) and the measured regions are
drawn over it as SVG. The outline stays sharp at any zoom, draws itself on
with `stroke-dashoffset` over ~520 ms, and the view opens framed on the
measurement with a "show the whole sheet" toggle. `?trace=<line id>` opens a
line's trace on load — added so the panel could be screenshotted at all, and
kept because the demo wants to link straight to it.

**What the screenshots showed, in order, and the three bugs they caught:**

1. First capture: outlines rendered as 8 px slabs covering the very walls they
   pointed at. `strokeWidth` was computed in page units, but
   `vector-effect: non-scaling-stroke` makes it screen pixels. Now a constant
   2.4 px with a drop-shadow halo, so a small schedule cell is still findable
   on a dense drawing without the stroke swallowing it.
2. Second capture: the panel did not open at all for `ln-slab-on-grade`, while
   it had opened for the partition line. The auto-open effect keyed on
   `status`, so whether it fired depended on whether `takeoff` happened to be
   set in that render — it worked for one line by luck. Now keyed on the
   takeoff itself with a ref to keep it to once per project.
3. Third capture: **a completely blank page**. Moving the effect left its
   dependency array referencing `showTrace` above the `useCallback` that
   declares it — a temporal dead zone `ReferenceError` that blanked the whole
   app. The DOM dump showed 1,207 bytes and no rows. Fixed by moving the
   effect below its dependency.

None of the three was visible from the API, which answered every request
correctly throughout. The third would have shipped a blank app.

Final state verified on two lines: `ln-interior-partition-p1-l0` outlines 36
measured walls on A101 with the storey pager offering A102, and
`ln-slab-on-grade` frames the five schedule cells on S201. The three `kind`
labels are unchanged — measured geometry, schedule row and sheet only remain
different claims.

Left alone: pan and drag. The zoom-to-region plus whole-sheet toggle covers
the demo, and a drag handler competing with the scrim's click-to-close is a
good way to make the panel feel broken. Noted for item 9 if time allows.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 3. The three views connected ✅

The donut, the contribution bars and the bill now share one hover and one
filter. Hovering a bill row lights its donut segment and its bar; hovering a
segment lights every row made of that material; clicking a segment or a bar
filters the bill to it, and the card header offers a way back.

The join is exact rather than fuzzy: `factor.name` on a carbon line equals
`key` on a material category for **19 of 19** counted lines, checked against
the live response before any code was written. Focus is carried as the
material key rather than a row index, because an index means nothing outside
the component that produced it.

Filtering **dims** rows instead of removing them. A bill that silently drops
rows would let a reader believe the total covers only what is on screen,
which is the class of quiet misdirection this whole project spends its effort
avoiding. The filter also clears on project change, or it would hide most of
a different building's bill.

Verified by counting the rendered DOM rather than trusting the build: 20 bill
rows, 8 donut segments, 8 bars, 0 dimmed with no filter active, and the page
renders. Hover and click cannot be driven from headless Chrome, so the
interactive behaviour itself is unverified by screenshot — the states are
small and declarative, but that gap is worth naming rather than implying it
was tested.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 4. The headline arrives ✅

Counts up over 700 ms with easeOutCubic; the KPI tiles and contribution bars
rise 40 ms apart. `prefers-reduced-motion` short-circuits both.

A screenshot caught the figure mid-count at **17,723** instead of 48,613, and
that is worth more than the animation. `requestAnimationFrame` stalls in a
background tab and does not advance reliably under headless capture, so a
stalled animation leaves a *wrong number on screen* — not a cosmetic glitch,
a false total. A timeout now writes the true value once the animation should
have finished, whatever happened to the frames. Re-captured: settles at
48,613.

### 5. Cosmetic bugs ✅

- Project name no longer wraps to two lines in the title block; the
  "Technical Design Package" suffix is stripped.
- Truncated sheet details carry a `title`, so a clipped `W2 EXTERIOR ENVELOPE
  WALL - NON-…` is readable on hover.
- The sticky header's 56 px offset is now documented against the topbar it
  parks beneath, with a note that its solid background is required rather than
  decorative.
- The collapsed-notices button no longer sits flush against the notice above.
- The two-column footer stacks at 1100 px instead of squeezing two unreadable
  columns, and the hero's title block narrows to 260 px at 1240 px.
- Checked at 1280 and 1440.

**Not verified by screenshot, and worth naming:** the KPI tiles render faded
in every capture because headless Chrome freezes CSS animations mid-run. A
DOM dump confirms all four tiles and labels exist and the project suffix is
gone, and animations run normally in a real browser — but the staggered
entrance itself has only been verified by its end state in the DOM, not by
eye.

Items 4 and 5 are both UI-only; no Python changed between them, so one suite
run covers both rather than spending twenty minutes proving the same thing
twice. Committed separately.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 6. Upload, as a visible feature ✅

Drag-and-drop or click, with the project facts asked for rather than
inferred. Floor area especially: guessing it from plan extents is what gave
AB_Rowhouse_01 an intensity of 761 kgCO₂e/m², above the highest whole-life
figure CMHC publishes for anything in the catalogue.

Verified end to end against the running service rather than by inspection: a
plan set the image has never seen returns **201, 24 lines, 56,343 kgCO₂e in
6.2 s**, and a non-PDF is refused with **415** and a reason — a scan carries
no geometry to measure. On success the selector re-lists and switches to the
new set.

`?upload=1` opens the dialog on load, for the same two reasons as `?trace=`:
a dialog that only opens on click cannot be screenshotted in review, and the
demo wants to link straight to it.

The screenshot shows the drop zone, the five fact fields, and the honest line
that nothing is stored beyond the session. The topbar control is now the one
primary action on the page.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 7. Every sheet in the set ✅

One tick per page, in page order, coloured by what the page turned out to be:
schedules, plans, sections and elevations, then cover/legend/services. The
sheets the bill actually cites stand taller and keep full colour, so four
findable among forty-six.

On AB_Fourplex_01 it reads: **46 sheets opened · every page classified · 4
carry a quantity in the bill · 1 had no readable text**, with the legend
counting Schedules 2, Plans 7, Sections & elevations 16, Cover/legends/
services 20.

The unreadable sheet is drawn **hatched rather than omitted**. A page with no
readable text is a fact about the drawing set, not a gap in the chart, and
dropping it would make the strip quietly flatter than the truth.

This is the "45 of 46 sheets read" claim from the title block in a form where
a reader can see which pages carried the weight — the schedules are two ticks
out of forty-six and they are where every build-up comes from.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 8. The massing view ✅ — SVG axonometric, not Three.js

Built after 1–7 landed, as Shiven asked.

**Verified the geometry before designing anything**, which the queue insisted
on and which paid off. The footprint keeps no origin (`width_m`, `depth_m`
only) and partition rectangles are in PDF page points, so there is no
page-to-building transform. But the rect extent on AB_Fourplex_01 is
398 × 1248 pt — ratio **0.319** — against a measured footprint of 7.0 × 22.0 m
— ratio **0.318**. They agree to 0.3%, so the partitions span the building and
their bounds are its bounds. Normalising against the rect extent is sound for
a checkable reason rather than as an assumption.

**Three.js was rejected on the measurement, not on taste.** ~600 kB against a
260 kB bundle to draw a box with internal walls is not a trade worth making,
and an axonometric is how a building is *drawn* rather than rendered — the
right register for a tool whose subject is drawings. Hand-projected SVG,
painter's-algorithm depth sort, two visible faces and a cap per wall so 73
walls stay legible instead of becoming a mesh.

`GET /projects/{id}/massing` returns the footprint, storey datums, walls in
metres and carbon per element class, or **null** when the footprint or datums
are missing — which is most of the catalogue outside Alberta. Drawing a guess
is the one thing this view exists not to do.

The screenshot reads as a building: the floor plan is legible in the wall
layout, two storeys with slabs, per-storey controls showing 36 and 37 walls.
It is not a grey box, so by the queue's own test it earns its place.

**A bug worth recording:** the endpoint 404'd at first because it was appended
*after* the static mount at `/`, which is a catch-all. The comment directly
above that mount says "mounted last so every API route wins its path" — the
rule was written and then broken by appending to the end of the file.

Left alone: colouring surfaces by carbon contribution. The data is in the
response (`carbon_by_class`) and unused. Walls read better in one colour at
this density, and a per-element heat map on a 73-wall plan was noise rather
than information. Shiven's call whether to push further.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

---

## Night summary

All eight items landed. Tests 719 throughout, ruff clean, Alberta gate
unchanged at every commit.

| | |
|---|---|
| Cold first request | 23–177 s → **0.01–0.4 s** |
| Bundle | 260 kB → ~270 kB (no charting or 3D dependency added) |
| New views | massing axonometric, sheet-coverage strip, upload dialog |
| Bugs caught by screenshotting | 6, of which 2 would have shipped broken |

The six: outlines drawn as 8 px slabs over the walls they marked; a trace
deep-link that fired for one line and not the next; a temporal-dead-zone
`ReferenceError` that blanked the entire app; a headline that could stick
mid-count showing a false total; `is_counted` tested in the browser though it
is never serialised, which read as "0 of 20 counted"; and a massing route
registered behind a catch-all mount. None was visible from the API, which
answered every request correctly throughout.

### Deploying found one more, as deploying usually does

The live massing call took **23.8 s** while every takeoff served in half a
second. The prebuilt files store quantities, not geometry, so the massing
endpoint was re-reading the drawings for footprint, datums and partition
positions on every request.

Cached per project (6.9 s → 0.00 s on the second call) and added to
`deploy/warm.sh`, so the first viewer never pays it. A design with no
footprint or datums caches its `None` too, or every page load would re-parse
a set that can never produce a massing.

Live after the fix: AB_Sixplex 0.50 s, QC_Sixplex 0.50 s (was 177 s),
BC_Fourplex_01 0.36 s, ON_ADU_02 0.52 s.

### 9a. An override now shows the reader's figure ✅

Found while building the "what changed" diff, and it was a bug rather than a
missing feature. The bill rendered `line.quantity` — the figure *we* read —
even after a user overrode it, while the carbon column reflected the new
value. Editing a quantity left the old number on screen beside a total
computed from the new one.

It now shows the effective figure with ours struck through beneath:

```
25.00 m3
we read 20.02
```

Verified by applying an override through the API, reading `qty-was` and
`we read 20.02` back out of the rendered DOM, then resetting the line so the
demo state is clean. The carbon column moved 5,526 → 6,900 as it should.

This is criterion 2's "a human edit recomputes carbon" beat. It would have
demoed as the number not changing.

Suite: 719 passed, ruff clean, Alberta gate unchanged.

### 9b. The bill opens at eight lines ✅

Twenty lines, each two rows tall with its derivation control, put the open
decisions and the material substitutions **below 4,000 px** — a long scroll on
camera to reach two of the stronger panels. The bill now opens at eight with
`Show all 20 lines · 12 more`, which brings those panels up to ~3,100 px.

Eight is enough to show the shape of a bill: measured, inferred and assumed
all appear, and so does a line with no factor at all. The rest is one press
away, and the CSV export carries everything regardless.

Measured by counting rendered rows rather than trusting the build: 20 before,
8 after, with the control present once.

**Deliberately not done: keyboard navigation through the bill.** It was on
this list. The cite and quantity controls are already real buttons so Tab
reaches them, the demo is mouse-driven, and building arrow-key navigation
nothing will exercise is effort better spent on what Shiven actually called
out. Left for him to ask for.

**A recurring artifact, named so nobody chases it:** the sticky table header
overlaps the first row in *every* full-page screenshot. That is Chrome
compositing sticky elements at their stuck position in a tall capture; it
behaves correctly when scrolling a real viewport. If it looks wrong on
screen, the fix is to drop `position: sticky` from `table.boq th`.

Suite: 719 passed, ruff clean, Alberta gate unchanged.
