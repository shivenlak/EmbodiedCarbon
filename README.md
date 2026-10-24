# Embodied Carbon — automated takeoff-to-carbon for residential plan sets

Vector PDF plan set in → traceable bill of quantities + A1–A3 whole-building
carbon estimate out, with an interface for testing material substitutions.

Built for the Edmonton Unlimited **Built World Tech — Venture Pilots 2026**
challenge *"Automated Embodied Carbon Accounting for Residential Builders"*
(sponsor: Landmark Homes).

- **[RESEARCH.md](RESEARCH.md)** — what the data actually contains. Read this first; every number in it was measured.
- **[docs/PLAN.md](docs/PLAN.md)** — the build plan, quality bars per rubric criterion, checkpoints and cut lines.

## ⚠️ The data is not in this repo

The CMHC Housing Design Catalogue (2.7 GB, 52 design packages) is licence-restricted.
CMHC's Terms and Conditions grant only a limited licence to adapt the Designs for a
specific Canadian building project and **expressly prohibit redistribution** — pushing
them to GitHub would be distribution. See [RESEARCH.md §7](RESEARCH.md).

The catalogue lives outside the repo and is found via `$EC_DATA`:

```bash
export EC_DATA=~/ec-data/cmhc      # default; 52 package directories inside
python scripts/fetch_data.py --check
```

`.gitignore` blocks `CMHC Plans/`, `*.ifc`, `*.h2k`, `*.dwg` and `reference/`.
**Never `git add -f` any of them.**

## Setup

```bash
brew install python@3.13 poppler          # system python 3.9 is too old for the stack
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python scripts/env_check.py     # verifies deps + data + a real parse
```

## Layout

```
ecarbon/
  config.py     catalogue discovery; $EC_DATA resolution
  models.py     THE DATA CONTRACT -- change here first, then tell the other person
  intake/       Stage 1: open set, page inventory, toolchain detection, gap report
  geometry/     vector paths, CTM resolution, scale calibration
  extract/      element detectors, dimension + schedule parsing
  takeoff/      Stage 2: bill of quantities, confidence labelling
  carbon/       Stage 3: factor store, provider interface, module guard, totals
  bench/        ground truth (IFC / HOT2000 / Building Performance Reports) + scoring
  api/          FastAPI
web/            React (Vite)
scripts/        env_check.py, fetch_data.py, inventory_all.py, run_bench.py
```

## The one interface that matters

`ecarbon/models.py` defines `TakeoffResult` (extraction output) and `CarbonResult`
(carbon output, keyed by takeoff line id). Extraction and carbon/UI are developed
against `tests/fixtures/takeoff_example.json` so neither side blocks the other.

Two invariants the rubric scores directly, both enforced by validators:

- a line labelled `assumed` **must** document its assumption
- a carbon line with no factor **must** give a `missing_reason`, and is excluded
  from the total rather than silently zeroed

## Running things

```bash
.venv/bin/python scripts/inventory_all.py AB            # Stage 1 inventory, Alberta
.venv/bin/python scripts/inventory_all.py --json out/inventory.json
.venv/bin/python -m pytest
.venv/bin/uvicorn ecarbon.api.main:app --reload
```

## Scope boundary

**A1–A3, cradle-to-gate only.** Several sources cover more or fewer modules. Only
like-for-like modules may be summed and the module scope of every factor stays visible
to the user. The CMHC Building Performance Reports publish A1–A5 + B4–B5 + C2–C4 totals —
those are *not* directly comparable to our A1–A3 figure, and the UI says so.

## Attribution

Design data adapted from Canada Mortgage and Housing Corporation, Housing Design
Catalogue. This does not constitute an endorsement by CMHC of this product or of the
accuracy or quality of the information it contains.
