# Handoff — read this first

Written for whoever picks this up next, including an AI session starting
cold. It carries the context that is **not** recoverable from the code, and
names the things that will bite you if you don't know them.

State at handoff: **722 tests passing, ruff clean, deployed and live.**

---

## The five things that will cost you if you don't know them

### 1. The catalogue must never be committed. The repo is public.

The CMHC Housing Design Catalogue (2.7 GB) is licence-restricted: CMHC
prohibit "distributing, licensing, selling, or otherwise making available any
Designs". **This repository is public**, so a commit of that data is ungated
public distribution.

It lives outside the repo, found by `$EC_DATA`:

```bash
export EC_DATA=~/ec-data/cmhc     # 52 package directories inside
```

Before every commit, screen the staged list:

```bash
git status --short | grep -iE "CMHC|\.ifc|\.h2k|\.dwg|\.ctb|reference/|deploy/data|_prebuilt|web/dist"
```

A hit means stop. `deploy/data/` and `web/dist/` are gitignored on purpose —
they are the staged plan sets and the built bundle.

**Separate decision, already made:** shipping plan sets *inside the deployed
image* is fine, and Shiven decided that deliberately. The image is built from
`deploy/data/`, which never enters git. Do not confuse the two.

### 2. `ecarbon/models.py` is a frozen contract

It is shared with the teammate's `mvp` branch. Don't edit it. If something
genuinely needs a field, say so rather than adding one — several features
here were deliberately built around it (the open-decisions endpoint, the
intensity check) precisely to avoid touching it.

### 3. Alberta is the scored region, and it has a gate

`tests/test_alberta_gate.py` pins Alberta's exact figures. Every extraction
module is shared, so a change made for one province silently moves another —
that has happened repeatedly. If a gate number moves, it is a regression
until proven otherwise, and the proof belongs in the commit message.

### 4. The caches live in machine memory. Warm after every deploy.

```bash
fly deploy --remote-only --ha=false
deploy/warm.sh          # NOT optional
```

Takeoffs are prebuilt into the image, but the massing, the traces, the sheet
renders and the open decisions are built on first request and cached in RAM.
A deploy throws all of that away. Skip the warm and the demo's key press —
clicking a sheet tag — takes 16 seconds instead of 0.2.

### 5. Look at the interface before believing a change worked

Eight bugs this project found came from screenshotting, not reasoning, and
three would have shipped broken:

- a `ReferenceError` that blanked the entire app (twice — both times a `const`
  read above its declaration, a temporal dead zone)
- a headline that could freeze mid-count, displaying a false total
- the bill showing the old quantity beside a recomputed total after an edit

```bash
cd web && npx vite build --logLevel error
cd .. && EC_DATA="$PWD/deploy/data" ECARBON_WARM=0 \
  .venv/bin/python -m uvicorn ecarbon.api.main:app --port 8000 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --disable-gpu --no-sandbox --hide-scrollbars --screenshot=/tmp/shot.png \
  --window-size=1500,1400 --virtual-time-budget=35000 \
  "http://localhost:8000/?plan=AB_Fourplex_01"
```

Then actually open the PNG. Deep links exist because dialogs can't otherwise
be reviewed: `?trace=<line id>`, `?upload=1`, `?view=carbon`, `?turn=<deg>`,
`?plan=<key>`.

---

## Where it stands

**Live, open, no credentials:** https://ecarbon.fly.dev

Submission 1 is due **Thu 29 Oct, 11:59 PM MT** and is judged on the build
only — implementation and business plans are scored at Submission 2 on 26
November. What this round scores: quantity extraction, carbon assessment and
traceability, drawing intake, interactive configuration, usability.

| | |
|---|---|
| Catalogue | 53 sets, **0 crashes** |
| Element coverage | median **52%**, Alberta **100%** on six of seven |
| Doors / windows vs IFC | median **0.0%** / **4.0%** |
| Footprint vs IFC | median **3.3%** |
| Partitions vs IFC | median **5.7%**, worst **+92%** |
| Reference design | AB_Fourplex_01 · 43,075 kgCO₂e · 37,536 excl. partitions · 140.8 kg/m² |

Every figure is printed by a script named beside it in
[benchmark.md](benchmark.md). Worst cases are published next to medians.

### What to read, in order

1. **[FOR_JUDGES.md](FOR_JUDGES.md)** — what the product does, in five minutes
2. **[demo_script.md](demo_script.md)** — the video, beat by beat, timed
3. **[benchmark.md](benchmark.md)** — every accuracy figure, including the
   regressions
4. **[OVERNIGHT_UI.md](OVERNIGHT_UI.md)** — the last build session's log: what
   was tried, what the screenshots showed, what was deliberately left alone

---

## What is left

**Before submitting** — all Shiven's:

1. Open the link in a private window (organisers' own pre-submit check).
2. Record the five-minute video. `demo_script.md` is ordered around quantity
   extraction, because the organisers said to lead with it.
3. Submit link + video. No credentials needed; say so in the form's Platform
   Credentials field.

**Deliberately not done**, with reasons in the logs rather than left looking
forgotten:

- **Dark mode.** Tokens exist in `:root`; nothing consumes them.
- **Keyboard navigation through the bill.** The cite and quantity controls are
  already real buttons, so Tab reaches them.
- **Pan and drag inside the trace panel.** Zoom-to-region plus a whole-sheet
  toggle covers the demo; a drag handler competing with the scrim's
  click-to-close makes a dialog feel broken.

**Known and unresolved**, published in the benchmark rather than hidden:

- **`W1` is 235 mm and `P3` is 235 mm** on AB_Fourplex_01, so depth alone
  cannot separate an exterior wall from a demising wall. A perimeter filter
  was written and measured; it changed nothing, and was removed rather than
  kept as a protection it does not provide.
- **Ontario reads 29% where it once read 42%**, and that is a correction, not
  a regression: the 13 points it lost were a roof assembly being read at 75%
  error. Coverage and correctness are different axes.
- **Ontario's mojibake repair is incomplete.** Tag-level repair works; layer
  text still contains glyph-shifted strings like `TKIKF"KPUWNCVKQP`.
- **46 "no thickness stated" refusals**, of which **41 sit on rows carrying a
  `VAR` cell** — the drawings decline to state those thicknesses. Not
  recoverable, but currently reported as "could not be read reliably" when
  the truth is "the drawing says it varies". Worth relabelling.

**The accuracy deep dive** Shiven asked for is partly done.
`scripts/audit_discards.py` reports what each stage throws away and how much
structure went with it. Its finding: the assemblies stage is near its
ceiling, and the biggest refusal category (99 of 172, "name looks like a
material") is **correctly** refused — keeping those blocks scores 86.4%
median error against 20.1% for cleanly-named ones. The hypothesis was tested
and rejected on measurement, and the result is recorded in the code so it is
not retried.

---

## Operational facts

```
app          ecarbon          region sjc        performance-2x, 4 GB
image        node build -> python:3.13-slim, pymupdf + numpy only
data         deploy/stage_data.py  -> deploy/data/   (gitignored)
prebuild     deploy/prebuild.py    -> deploy/data/_prebuilt/*.json
```

- `performance-2x` costs roughly $40/month pro-rated. It was chosen because
  parsing is pure CPU and shared cores made an upload take 137 s instead of
  20. One line in `fly.toml` drops it back after Demo Day.
- `ifcopenshell` and `pandas` are deliberately **absent from the image**. They
  belong to `ecarbon/bench/` and `scripts/`, which score the pipeline against
  the IFC models and never run in the service.
- A full upload → takeoff → carbon → trace cycle loads only `pymupdf` and
  `numpy`, and peaks near 900 MB, which is why builds are serialised behind a
  lock.

## How this project works, if you are going to add to it

The thing that makes it worth anything is that it refuses to guess. Gaps are
reported, confidence is labelled, and the same scale runs through the whole
interface: **measured** means off the linework, **inferred** means computed
from something the drawing states, **assumed** means a standard stood in.
Those are three different claims and they are never blurred.

Three concrete expressions of that, worth preserving:

- Cladding and roofing carry **no carbon**, because the drawings say
  "placeholder". The range is priced and the decision handed back.
- The total is reported **twice** — with and without the inferred partitions —
  because that run is measured off linework rather than read from a schedule.
- A trace says **how strong it is**: measured geometry, schedule row, or sheet
  only. Sheet-only highlights nothing rather than pointing at a guess.

If a change would make the tool quieter about its own uncertainty, it is
probably the wrong change.
