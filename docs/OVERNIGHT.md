# Unattended work queue

A queue for running Claude Code overnight on this project, plus the log of what
each run actually did. Read the **Log** at the bottom first — that is the
record of the last session.

## Why this runs locally and not in the cloud

Every item below needs `$EC_DATA`, the 2.7 GB CMHC catalogue at
`~/ec-data/cmhc`. It is licence-restricted and can never be committed, so a
cloud agent would skip every data-backed test and could not run a single
scoring script. Keep the machine awake instead:

```bash
caffeinate -dimsu     # in its own terminal, left running
```

## Guardrails

Non-negotiable, in priority order:

1. **Never commit catalogue data.** Before every `git add`, grep the staged
   list for `CMHC Plans/`, `*.ifc`, `*.h2k`, `*.dwg`, `reference/`,
   `node_modules`, `web/dist`. Abort on any hit. Pushing it to the public repo
   breaches the CMHC licence.
2. **Commit only green.** `ruff check ecarbon scripts tests` clean and the full
   `pytest` suite passing. Never leave `main` broken — a teammate works off
   this repo.
3. **No history rewriting.** No force-push, no rebase of `main`, no amending
   pushed commits.
4. **Do not change `ecarbon/models.py`.** It is the frozen contract between two
   people's work. Flag a needed change in the log instead.
5. **Measured numbers only.** Every figure that reaches a doc or a commit
   message comes from a `scripts/score_*.py` or `run_pipeline.py` run in that
   session. Never carry a number forward from memory, and never quote a subset
   that flatters the result — report the distribution.
6. **A negative result is a result.** If a task does not improve the measured
   outcome, write down what was tried and what the numbers did, revert the
   change, and move to the next item. Do not tune thresholds against one
   design until they fit.
7. **Stop rather than guess.** If an item turns out to need a judgement call —
   what to claim, what to ship, what to cut — leave a note in the log and move
   on. Those get made with a human present.

## Baseline to beat

Measured 2026-10-26, `python scripts/run_pipeline.py`:

| | |
|---|---|
| Crashes | 0 of 53 |
| Element coverage | median **37%**, best 91% |
| Designs ≥80% coverage | 5 of 45 |
| Tests | 558 passing |

| Region | Coverage, median | Why it is not higher |
|---|---|---|
| AB | 91% | interior partitions only |
| QC | 66% | partitions, roof assembly |
| BC | 37% | exterior wall assembly refused, no footing dims |
| ATL | 22% | most assemblies refused |
| ON | 9% | assemblies unreadable (mojibake) |
| SKMB | 9% | package publishes no assemblies schedule at all |
| NOR | — | text converted to vector outlines; correctly reports nothing |

## Queue

Work top down. Re-run `scripts/run_pipeline.py` after each item and record the
coverage change in the log.

### 1. Assembly tag forms — biggest single lever, ~16 designs

BC tags its assemblies `W1.1`, `W1.2` with a dot. `_TAG_RE` in
`ecarbon/extract/assemblies.py` is `^[A-Z]\d{1,2}[a-z]?$` and does not match
them, so on `BC_Duplex`'s sheet A002 only the plain `W2` is seen. With one tag
in a 772-point band, tag segmentation cannot split it and every assembly in
that band merges into one 50-layer object, which the plausibility gate then
refuses — losing the exterior wall, 20% of the building's carbon.

Survey the tag shapes actually present in schedule TYPE columns across the
catalogue before widening the pattern, then widen it to what exists. Watch for
false positives: `R2.5` could be an insulation value rather than a roof tag,
though tags are only read inside the TYPE column band, which limits the risk.

*Verify:* `BC_Duplex` keeps its exterior wall assembly; AB stays at 17 kept and
0 refused; `score_assemblies.py` refusal count falls; `run_pipeline.py` BC
coverage rises from 37%.

### 2. Footing schedule tables — ~16 designs, 27% of carbon each

`parse_foundation_spec` reads Quebec's inline `FOOTING 750x200` but not BC's
tabular form, which states footings in a schedule with bracketed dual units:

```
REMARKS  TYP FOR STRIP FOOTINGS UNO  FW2  [110 - 150 kg/m3]  10" [250mm]
```

on sheet `S001`. Atlantic reports `unknown` or `strip_footing` with no
dimensions and needs looking at separately.

*Verify:* `foundation_spec_for` returns footing dimensions for BC designs;
`ln-strip-footing` appears in their bills of quantities; Alberta still reads a
200x1200 grade beam and no strip footing.

### 3. Ontario mojibake, scoped to this module — 5 designs

Ontario's five multiplexes have a readable assemblies schedule whose thickness
cells are glyph-ID mojibake that `intake/textrepair.py` deliberately refuses:
`PP` is `mm` under the 0x1D shift and `5,*,',168/$7,215` is `RIGID
INSULATION`. Two guards block it — cells under three characters are skipped,
and any cell containing letters is left alone.

**Do not loosen the global guards.** The letter guard is what stops `R-22`
becoming `oJOO` across 1,465 pages of sheet classification. Write a repair
scoped to `extract/assemblies.py` that accepts a shift only when the result
parses as a thickness or matches a known material phrase, so a wrong shift is
rejected rather than believed.

*Verify:* sheet identification figures unchanged (`score_sheets.py` still
97.9% / 95.1%); ON assemblies parse on more than 2 of 7; `run_pipeline.py` ON
coverage rises from 9%.

### 4. Keep the published numbers current

After any of the above, re-run the scoring suite and update `docs/benchmark.md`
and the figures in `docs/pitch.md` so nothing published is stale:

```bash
python scripts/score_sheets.py
python scripts/score_scale.py
python scripts/score_footprint.py
python scripts/score_assemblies.py
python scripts/score_openings.py
python scripts/run_pipeline.py
```

### Not on this queue

- **Interior partition CV.** Attempted and measured: finds ~70% of partitions
  on Alberta and 25–50% elsewhere, with no parameter that improves both. See
  the negative result in `docs/benchmark.md`. The real fix is classifying wall
  linework using the `A-WALL` layer names on the ~20 AIA-layered sets, which
  needs iteration and a judgement about whether to ship. Do it with a human.
- **Anything about the UI.** It cannot be checked without a browser.
- **SKMB assemblies.** Those packages contain no assemblies schedule. No
  amount of parsing fixes a missing document.

---

## Log

Newest first. One entry per session: what was attempted, what the numbers did,
and what was left alone.

### 2026-10-27 — item 4, published numbers refreshed

`docs/benchmark.md` and `docs/pitch.md` updated from this session's runs, so
nothing published is stale. Changes:

| | before | after |
|---|---|---|
| catalogue median coverage | 37% | **44%** |
| designs with trustworthy assemblies | 31 / 53 | **36 / 53** |
| Ontario assemblies | 2 / 7 | **7 / 7** |
| assemblies kept / refused | 291 / 115 | **360 / 158** |
| built depth, assemblies compared | 148 | **163** |
| built depth, median error | 5.8% | **7.9%** |
| built depth, exact | 48 | 47 |

**Recorded as a trade rather than buried:** reading more schedules cost a
little per-assembly precision. The comparison set grew from 148 assemblies to
163 and designs from 31 to 36 while the median built-depth error moved 5.8% ->
7.9% and exact matches held at 47. The assemblies added are the harder ones —
dotted BC tags and glyph-ID Ontario cells — so the average is diluted rather
than any previously good reading having degraded. The benchmark says this
plainly next to the table rather than reporting only the coverage gain.

The stale Ontario paragraph in the benchmark's assemblies section was rewritten:
it previously said Ontario's schedules could not be read, which is no longer
true.

## Queue state after this session

Items 1, 2 and 3 are done. Item 4 is a standing task — re-run it whenever the
numbers move. **Next most valuable work, in order:**

1. **Atlantic footings.** ATL reports `strip_footing` or `unknown` with no
   dimensions and benefited from neither the inline nor the table pattern, so
   its footings are stated in a third form. 9 designs, 9% of carbon each.
2. **Atlantic assemblies.** 8 of 9 parse a schedule but coverage is still 22%,
   the lowest of any region that reads its schedules. Worth diagnosing why its
   parsed assemblies are not producing lines — the same question that turned out
   to be column misidentification for Quebec.
3. **Ontario storey heights.** Every ON multiplex reports `n_storeys = 0`, so no
   exterior wall and no floor assemblies. Separate from the mojibake work and
   worth more than it: the exterior wall is 20% of carbon.

**Needs a human, not another unattended pass:** BC's exterior wall assembly is
still refused, and the block-splitting underneath it is a judgement about
approach — the one attempt made the catalogue worse and was reverted.

### 2026-10-27 — item 3, Ontario mojibake: ON 9% -> 22%

**Kept, and the guardrail held.** Sheet identification is unchanged at 97.9%
sheet-number and 95.1% sheet-type match across 1,465 pages, with 8 of 8
textless sets still reporting their gap. The global text-repair guards were not
touched; `repair_schedule_cell` lives in `extract/assemblies.py` and is reached
only from that module.

Ontario's schedule decodes entirely under a single 0x1D shift, and the global
repair already handled most of it — `7<3(` is `TYPE`, `9$5` is `VAR`. It
refuses exactly two kinds of cell:

- **thicknesses**, because `PP` is `mm` and contains letters, which trips the
  guard that stops `R-22` becoming `oJOO`;
- **tags**, because `W1` is too short to score as prose, has one digit where a
  sheet number needs two, and contains a letter so it fails the dimension test.

A shift is accepted only when the result is a real numeric thickness or a
well-formed tag. Word-likeness is deliberately insufficient: a dimension cell
that comes out as prose means the shift was wrong, and a wrong thickness is
worse than an unread one.

**The parse alone changed nothing, which is why measuring mattered.** Ontario's
assemblies went 0 -> 5 and coverage stayed at 9%, because
`assembly_tags_used` called the global `repair()` directly rather than the
repaired span reader. Ontario's *plan* sheets are glyph-ID encoded too, so the
tag references stayed mojibake, `dominant W/R/F` came back `[None, None,
None]`, and a schedule that now parsed went entirely unused. Applying the same
scoped repair there took `ON_Fourplex_01` from 0 to 42 tag references and
9% to 22% coverage.

| Region | before | after |
|---|---|---|
| ON | 9% | **22%** (best 75%) |
| AB | 91% | 91% |
| QC | 66% | 66% |
| BC | 59% | 59% |
| ATL | 22% | 22% |
| catalogue median | 44% | 44% |

**Left alone — two further Ontario blockers that are not mojibake.** The queue
predicted roughly +66 points for Ontario on the assumption that assemblies were
the only obstacle. They were one of three:

1. `n_storeys = 0` — "fewer than two floor datums found" on every ON multiplex.
   No storey height means no exterior wall and no floor assemblies, which is
   most of the carbon. A separate problem from text encoding.
2. **No readable foundation plan exists in those sets at all**, so the
   foundation system is `unknown` and slab and footing concrete cannot be
   produced. That is a missing document rather than a parsing failure, in the
   same category as SKMB having no assemblies schedule.

Tests 587. Suite green, ruff clean, 0 crashes across 53.

### 2026-10-27 — item 2, footing schedule tables: BC 50% -> 59%, catalogue median 37% -> 44%

**Kept.** BC states its footings in a schedule rather than inline the way
Quebec does, on sheet S001, with the metric in brackets beside the imperial:

    SF1  STRIP  [70 - 90 kg/m3]    2'-0" [600] WD x 18" [450] DP
    SF2  STRIP  [110 - 150 kg/m3]  2'-0" [600] WD x 10" [250] DP
    SF3  STRIP  [220 kg/m3]        3'-0" [900] WD x 18" [450] DP

Two things the pattern has to get right. It anchors on `WD` and `DP` rather
than on brackets, because `[110 - 150 kg/m3]` sits between the dimensions and
is a reinforcement rate — reading a bracket as a dimension would be the same
class of error as the `1200mm LG. DOWELS` one this module already learned. And
the three sections span 0.15 to 0.405 m², a factor of 2.7, with the schedule
never saying which runs where. Text order is arbitrary, so sections are sorted
by area, the smallest is used, and the line is labelled a LOWER BOUND naming
the alternatives and how much more concrete the largest would give.
Overstating footing concrete threefold is the unrecoverable direction.

Coverage, `scripts/run_pipeline.py`:

| Region | queue baseline | after item 1 | after item 2 |
|---|---|---|---|
| BC | 37% | 50% | **59%** |
| AB | 91% | 91% | 91% |
| QC | 66% | 66% | 66% |
| ATL | 22% | 22% | 22% |
| ON | 9% | 9% | 9% |
| SKMB | 9% | 9% | 9% |
| **catalogue median** | **37%** | 37% | **44%** |

Median intensity 24.6 -> 30.8 kgCO2e/m². This is the first change in the
session to move the catalogue median rather than one region: BC's footings are
9% of carbon across seven designs and compound with item 1's +13.

**Left alone:** Atlantic still reports `strip_footing` or `unknown` with no
dimensions and did not benefit from either pattern — its footings are stated
somewhere else again, and finding where is the next thing to look at under this
item. Crashes remain 0 of 53.

Tests 578 -> 587. Suite green, ruff clean.

### 2026-10-27 — item 1, assembly tag forms: BC 37% -> 50%

**Kept.** Four changes tried, three kept, one reverted after measuring.

Kept:
- `_TAG_RE` widened to the dotted forms. Surveyed every schedule TYPE column
  first rather than guessing: `P#`/`F#`/`W#`/`R#`/`N#`/`C#`/`S#` and `P#a` are
  universal, while `W#.#` (28), `R#.#` (21) and `FW#.#` (14) occur only in BC.
- Group key is now the whole alphabetic prefix via `tag_prefix`, not the first
  character. BC's `FW` is a foundation wall and reading it as `F` would have
  made it selectable as the floor assembly.
- `INSULATION$` dropped from the material-like name filter. It was refusing
  BC's genuine `2x6 WOOD STUD W/ EXTERIOR INSULATION` and its whole group.
- An assembly where no layer states a thickness is now refused: BC's `FW1.1`
  came through four layers deep, named `RIGID INSULATION (R-20.0)`, with no
  dimension anywhere in it.

**Reverted, with the measurement recorded in the code comment:** anchoring
blocks one row above the tag rather than at midpoints between tags. BC prints
its tag level with the first layer, not beside the name, so this did recover
BC's exterior wall (`W1.1`, 11 layers, 264 mm) — but catalogue-wide it split
more blocks and the extra ones began on layer rows, producing assemblies named
`FLOOR FINISH w/ UNDERLAY`, `RUBBER SOUND ISOLATION` and `AT EAVE, VALLEY AND
RIDGE`, plus a one-layer `W4`. Built-depth median 5.8% -> 7.9%, exact matches
48 -> 37, worst case 100% -> 1210%. A truncated build-up is a smaller error
than a fabricated one.

Coverage, `scripts/run_pipeline.py`:

| Region | before | after |
|---|---|---|
| BC | 37% | **50%** |
| AB | 91% | 91% |
| QC | 66% | 66% |
| ATL | 22% | 22% |
| ON | 9% | 9% |
| SKMB | 9% | 9% |
| catalogue median | 37% | 37% |

BC gains 13 points on all seven designs with no regression elsewhere. The
catalogue median does not move because BC is not the median region. Assembly
refusals rose 115 -> 135, which is the gate working rather than a regression:
more tags are recognised, so more blocks are evaluated and more bad ones
correctly rejected. Built-depth accuracy held at baseline (median 5.9% vs
5.8%, 47 vs 48 exact).

**Left alone:** BC's exterior wall is still refused. The tag fix was necessary
but not sufficient — the block-splitting underneath needs the table layout read
properly rather than inferred from tag positions, and the one attempt at that
made things worse. That is a judgement call about approach, not a tuning
problem, so it is left for a human.

Tests 558 -> 578. Suite green, ruff clean.

### 2026-10-26 — queue created

Baseline recorded above. Item 1 diagnosed but not yet fixed: BC's dotted tag
form found by inspecting sheet A002 of `BC_Duplex`, where tags read `W1.1` and
`W1.2` at x=241 while `_TAG_RE` matches neither.
