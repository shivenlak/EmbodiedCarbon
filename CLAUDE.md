# ecarbon — working notes

Vector PDF plan set in → traceable bill of quantities + A1–A3 embodied carbon
out. Built for the Edmonton Unlimited *Built World Tech* challenge, sponsor
Landmark Homes.

**Read [docs/HANDOFF.md](docs/HANDOFF.md) before changing anything.** It
carries the context that is not recoverable from the code.

State: **722 tests passing, ruff clean**, deployed at https://ecarbon.fly.dev
(open, no credentials).

---

## Hard constraints

**The CMHC catalogue must never be committed. This repo is public.**
CMHC prohibit "distributing, licensing, selling, or otherwise making
available any Designs", so a commit here is ungated public distribution. The
data lives at `$EC_DATA` (default `~/ec-data/cmhc`). Before every commit:

```bash
git status --short | grep -iE "CMHC|\.ifc|\.h2k|\.dwg|\.ctb|reference/|deploy/data|_prebuilt|web/dist"
```

A hit means stop. Shipping plan sets inside the *deployed image* is a
separate thing and is fine — the image builds from `deploy/data/`, which is
gitignored.

**`ecarbon/models.py` is a frozen contract** shared with the `mvp` branch.
Don't edit it; work around it and say so.

**`tests/test_alberta_gate.py` pins the scored region.** Every extraction
module is shared, so a change for one province silently moves another. If a
gate number moves it is a regression until proven otherwise, and the proof
goes in the commit message.

**Never rewrite history or force-push.** A teammate works on `origin/mvp`.

## Before you believe a UI change worked, look at it

Eight bugs here were found by screenshotting rather than reasoning; three
would have shipped broken, including two `ReferenceError`s that blanked the
entire app (both a `const` read above its declaration). Build, serve,
screenshot, and **open the PNG**:

```bash
cd web && npx vite build --logLevel error
cd .. && EC_DATA="$PWD/deploy/data" ECARBON_WARM=0 \
  .venv/bin/python -m uvicorn ecarbon.api.main:app --port 8000 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --disable-gpu --no-sandbox --hide-scrollbars --screenshot=/tmp/shot.png \
  --window-size=1500,1400 --virtual-time-budget=35000 \
  "http://localhost:8000/?plan=AB_Fourplex_01"
```

Deep links exist so dialogs can be reviewed at all: `?plan=`, `?trace=`,
`?upload=1`, `?view=carbon`, `?turn=<deg>`.

## Commands

```bash
.venv/bin/python -m pytest                 # 722 tests, ~10 min
.venv/bin/python -m ruff check ecarbon scripts tests deploy
.venv/bin/python scripts/run_pipeline.py   # all 53 sets
.venv/bin/python scripts/audit_discards.py # what each stage throws away

fly deploy --remote-only --ha=false
deploy/warm.sh                             # NOT optional after a deploy
```

Caches live in machine memory. Takeoffs are prebuilt into the image, but
massing, traces, sheet renders and open decisions build on first request.
Skip the warm and clicking a sheet tag takes 16 s instead of 0.2.

## What this project is for

It refuses to guess, and that is the point rather than a side effect.

- **measured** = off the linework, **inferred** = computed from something the
  drawing states, **assumed** = a standard stood in. Three different claims,
  never blurred.
- Cladding and roofing carry no carbon, because the drawings say
  "placeholder". The range is priced and the decision handed back.
- The total is given twice, with and without the inferred partitions.
- A trace says how strong it is; sheet-only highlights nothing rather than
  pointing at a guess.

A change that makes the tool quieter about its own uncertainty is probably
the wrong change.
