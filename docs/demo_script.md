# Five-minute demo — running order

Submission 1 is judged on the build alone. The implementation and business
plans are scored at Submission 2 on 26 November, so they are mentioned in
passing or not at all.

**What this round scores, in the organisers' order:** quantity extraction,
carbon assessment and traceability, drawing intake, interactive configuration,
general usability and automation. They said plainly to start with the most
important, which for Embodied Carbon is quantity extraction — so this opens on
the bill of quantities, not on the philosophy.

Their other three asks, each answered by a beat below:

- **Show your work** — quantities that trace to their source sheet and detail.
- **Show what the tool doesn't know** — gaps and low confidence, flagged
  rather than hallucinated over.
- **Show range** — more than one plan set.
- **Bring evidence** — the benchmark and the test suite.

"Back end" here means the reviewer's side: how someone checks our work. For a
takeoff tool that is the addressable data and the export, not a database
screen.

**Say the figures the live site shows.** Open
https://ecarbon.fly.dev/?plan=AB_Fourplex_01 before the take and read the
headline. The partition fix of 28 October changes five numbers in this script
and nothing else; the beats below quote the corrected column.

| Beat | Headline reads **43,075** (fix deployed) | Headline reads **48,613** (not yet deployed) |
|---|---|---|
| 2:35 total | 43,075 kgCO₂e | 48,613 kgCO₂e |
| 2:35 without partitions | 37,536 | 37,536 |
| intensity, if quoted | 140.8 kg/m² | 158.9 kg/m² |
| 3:45 cellulose, wall + roof + floor | 14.6 percent | 12.9 percent |
| 3:45 40% fly-ash mix, slab + footing | 8.0 percent | 7.1 percent |

If it reads 48,613, do not mention the correction on camera: the judges will
see that number, and `docs/FOR_JUDGES.md` explains the difference.

**Before recording:**

1. The Fly card must be on the account, or the machine stops five minutes
   after each deploy and the link dies mid-take.
2. `fly deploy --remote-only --ha=false`, then `deploy/warm.sh`. **The warm
   is not optional** — it builds the massing and every trace, and without it
   the demo's key press takes 16 seconds instead of 0.2.
3. Have a plan set on the desktop that is **not** one of the five bundled.
   `AB_Rowhouse_01` is the best choice if you have it: it exercises the
   floor-area correction live, where the stated 74 m² is replaced by the
   286 m² the drawings depict. Otherwise `AB_Rowhouse_02_Drawings.pdf`
   (10 MB, Alberta, so full coverage): rehearsed locally on 28 October, it
   returns 20 lines and 22 notices in 13 s on a laptop. Upload it once
   before the take — anything uploaded stays in every visitor's plan list
   until the machine restarts, so one rehearsal upload is enough.

Takeoffs are prebuilt into the image, so a bundled design answers in about
half a second. The massing view is built on first request and cached, which
`deploy/warm.sh` now covers — skip the warm and the first viewer waits
twenty seconds for it.

Deep links, so no take depends on finding a row:

```
?plan=AB_Fourplex_01
?plan=AB_Fourplex_01&trace=ln-interior-partition-p1-l0   # the money shot
?plan=AB_Fourplex_01&upload=1
```

---

## 0:00 — The problem, in fifteen seconds

> "A builder wants the embodied carbon of a plan set. Today that means a
> manual takeoff, handed to an LCA consultant, and a report weeks later. This
> takes the PDF."

Open https://ecarbon.fly.dev. No sign-in — the link just works.

Keep this short. The organisers asked for quantity extraction first, and it is
the heaviest criterion on the sheet.

## 0:15 — Quantity extraction, which is what this round scores

The site opens on the 3D model. Drag to turn it once, slowly.

> "This is the takeoff, drawn: the footprint we measured, the storeys at the
> datums we read from the sections, and seventy-three partition walls counted
> off the plans."

Point at **Measured from the drawings** beside the model.

> "Twenty lines off a forty-six page set. Slab, footings, exterior wall,
> windows, doors, every assembly layer, interior partitions. Each one carries
> what it is, how much, how we know, and the sheet it came from."

Point at the basis chips.

> "Measured means we measured it off the linework. Inferred means we computed
> it from something the drawing states. Assumed means the drawing was silent
> and a standard stood in. Those are three different claims and we never blur
> them."

## 0:50 — Traceability: press a sheet tag

Press **Slab on grade · S201** in the panel beside the model.

> "Every quantity traces to its sheet and detail. It opens zoomed to what was
> read, because a thirty-six by twenty-four inch sheet scaled into a window is
> a grey haze."

Then press **Interior partitions · 73 walls**, and switch A101 / A102.

> "A different claim, labelled differently. These outlines *are* the
> measurement — one rectangle per wall counted, on each storey. Seventy-three
> walls, measured off the plan linework, and you can see every one of them."

This is the strongest frame in the product. Do not rush it.

## 1:40 — Accuracy, with the worst cases shown

> "Against the 3D models that ship with the catalogue: door counts exact,
> window areas within four percent, footprint within three. Partition run
> length within six percent, worst case ninety-two — and that worst case is
> published, not buried. The benchmark reports medians next to worst cases,
> because a median alone hides the designs where this does badly, and those
> are the ones a builder needs to know about."

## 2:05 — What the tool does not know

Press **Review notes** in the sidebar.

> "Nineteen notices, and they come before the number. The drawings say
> 'cladding placeholder' — CMHC deliberately leaves it unspecified, so we do
> not pick one. This design numbers its two accessibility options A101 and
> A102; read both and you count that floor twice. And four partition-measuring
> approaches that failed before the fifth worked, published, because if you
> are deciding whether to trust the least certain line you should know it was
> hard to get."

Press **Options** in the sidebar.

> "Cladding and roofing carry no carbon at all. We price the range — 1,980 to
> 3,774 — and hand the decision back rather than defaulting one and saying
> nothing."

## 2:35 — The carbon, and the scope discipline

> "43,075 kgCO₂e. And 37,536 without the interior partitions, because that run
> is measured off linework rather than read from a schedule — the least
> certain quantity here, so you get both figures.
>
> A1 to A3, product stage only. CMHC publishes 162 tonnes for this building,
> but that bundles construction, sixty years of replacement and demolition.
> Summing across module scopes is the mistake this challenge tests for, so the
> engine raises rather than adding them."

## 3:00 — The model, in carbon

Back to **3D model**, press **Carbon intensity**.

> "Every surface coloured by what it carries per square metre. And because the
> model is drawn from what we read, if we read it wrong you can see that we
> read it wrong — on one of the ADUs our partitions over-count by
> ninety-two percent, and you would see walls with no room between them."

Toggle Storey 1 / Storey 2.

## 3:20 — Every sheet, and an edit

On **Review notes**, below the notices:

> "Forty-six sheets, all opened and classified. Four carry a quantity. One had
> no readable text and is drawn hatched rather than left out."

Then on **Bill of quantities**, edit a wall quantity.

> "An estimator disagrees, types their figure, carbon recomputes in nine
> milliseconds — and we keep ours beside it, struck through, so the correction
> is visible rather than silent."

## 3:45 — Interactive configuration

On **Options**:

> "Substitutions ranked by what they actually save against these quantities.
> Cellulose for mineral wool, across the wall, roof and floor together, 14.6
> percent of the total. The fly-ash concrete mix is 36.6 percent less carbon per
> cubic metre, which is 8.0 percent here, slab and footing together —
> we quote both, because quoted only the first way it reads five times larger
> than it is."

## 4:05 — The reviewer's side

The judges asked to see the back end. For this product that is the surface a
reviewer checks our work from, not a database screen.

> "Everything a reviewer needs to audit this is addressable. The bill, the
> carbon result, the trace with its bounding boxes, the overrides — same
> credentials, same origin."

Open `/docs` briefly, then show **Download CSV** and **Export report** (the
whole takeoff as one printable report).

> "The CSV carries every line with its sheet, detail, basis and confidence, so
> a reviewer can check our work in their own spreadsheet. The interface is a
> client. The record is the data."

## 4:25 — Show range: a second plan set

Switch the selector to **QC Sixplex** or **BC Fourplex 01**.

> "Different province, different firm, different drafting conventions. Quebec
> reaches seventy-four percent of the building, British Columbia sixty-seven —
> and where coverage is partial the interface says so before you read the
> total."

Then press **Upload a plan set** and drag in a set that is **not** bundled.

> "And nothing here is specialised to the designs we shipped. Same gap report,
> same bill, same traceability, on a set this service has never opened — which
> is the only test that counts, because Landmark's sets are ones we have never
> seen either."

**Cut here.** A 6–11 MB set takes one to two minutes to parse on a shared CPU.
Start the upload, cut to the finished result, and say the figure out loud —
do not hold a static screen for ninety seconds of a five-minute video.

## 4:50 — Close

> "Zero crashes across all fifty-three catalogue sets. Door counts exact
> against the reference models, median element coverage fifty-two percent and
> a hundred on the region we developed against. Seven hundred and twenty-two
> tests. And the published benchmark includes the worst cases and the
> regressions, because a benchmark that only reports its wins is not a
> benchmark."

---

## If something goes wrong on camera

- **"The reader is not running"** → the service is down or still starting.
  There is no sign-in any more, so this is not a credentials problem.
- **A takeoff takes 20+ seconds** → the machine restarted, so the prebuilt
  files are being read but the in-memory caches are empty. Run
  `deploy/warm.sh`.
- **The massing panel is missing** → it returns nothing when a design has no
  footprint or storey datums, which is most of the catalogue outside Alberta.
  That is deliberate; demo it on an Alberta set.
- **The massing panel takes 20 seconds** → it is built on first request.
  `deploy/warm.sh` covers it.
- **502 on a big design** → Fly's proxy timed out a cold build. Warm first;
  warming runs inside the machine specifically to avoid this.
- **The link dies partway through** → the Fly trial stops the machine after
  five minutes. There is no recovering from this mid-take; the card has to be
  on the account before recording.

## Before you submit

The organisers asked for these explicitly:

- **Open the link in a private window.** There is no sign-in; the private
  window is the check that nothing depends on your own session or cache.
- **Platform credentials:** none. Say so in the form's credentials field.
- **Keep it live.** Without a card on the Fly account the machine stops five
  minutes after each deploy, which fails "keep your solution live and
  accessible" on its own.
- Re-run `deploy/warm.sh` after the final deploy so the first judge through
  does not wait.

## What not to claim

- Do not call the catalogue median "accuracy" — it is element coverage.
- Do not compare our A1–A3 figure to CMHC's published whole-life total without
  saying the module scopes differ. The engine refuses to sum them; the demo
  should not blur them either.
- Do not say "every province works." Eight sets produce nothing, and the
  benchmark says so.
- Do not call the massing a model of the building. It is a massing of what was
  read: a measured box, measured datums and counted partitions. Saying "model"
  invites a question about geometry we do not claim to have.
