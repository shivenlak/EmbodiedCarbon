# For judges

**Live:** https://ecarbon.fly.dev — **no sign-in, nothing to enter.** Open the
link and it works.

> **A correction, found 28 October.** Interior partition *area* was being
> multiplied by the height of the whole building rather than of one storey, so
> every partition was counted once per storey. The IFC models caught it:
> AB_Rowhouse_02 read 1,203 m² of partition against the model's 576 (now 602),
> AB_Sixplex 2,029 against 738 (now 676). Every figure on this page is the
> corrected one. AB_Fourplex_01 moves from 48,613 to **43,075 kgCO₂e**, and the
> figure without partitions stays at exactly **37,536**, which is how we know
> nothing else moved. If the live site still shows 48,613, it is serving the
> build from before the fix, which differs only in the partition lines.
> ([the fix and its evidence](https://github.com/shivenlak/EmbodiedCarbon/pull/3))

A vector PDF plan set goes in. A traceable bill of quantities and an A1–A3
embodied carbon figure come out, with every quantity linked back to the sheet
it was read from.

---

## Five minutes, in order

**1. Read the gap report before the number.** The page leads with *"What we
could not read"*, not the total. On `AB Fourplex 01` that is 19 notices: a
cladding layer the drawings leave unspecified, a storey whose two accessibility
options would double-count if both were read, four partition-measurement
approaches that failed before the fifth worked. A low total that does not
announce itself as partial is indistinguishable from a good one.

**2. The total is given twice.** 43,075 kgCO₂e, and 37,536 without the inferred
interior partitions. That one run is measured off the plan linework rather than
read from a schedule — it is the least certain quantity in the bill, so the
figure without it sits beside the figure with it.

**3. Click any sheet tag in the bill of quantities.** The source sheet opens
with the region outlined, and the panel says how strong that trace is:

- *Measured here* — the outlined rectangles **are** the measurement. Interior
  partitions keep one rectangle per wall counted.
- *Read from this* — the schedule text the figure was computed from.
- *Sheet only* — right sheet, region not located, and **nothing is
  highlighted** rather than pointing at a guess.

**4. Decisions still open.** Cladding and roofing carry no carbon, because
CMHC's drawings say "cladding placeholder" and "roofing placeholder". We do not
pick one. The range is priced — cladding 1,980–3,774 kgCO₂e, roofing
1,371–2,433 — and the decision is handed back. This is kept separate from
substitutions on purpose: a substitution replaces a material somebody chose,
this is a choice nobody has made yet.

**5. Upload your own plan set.** Any vector PDF from the public CMHC catalogue,
or a builder's own. Nothing about the pipeline is specialised to the designs
bundled here — the gap report, bill of quantities, click-to-trace and
substitutions all work identically on a set the service has never seen.

Expect **one to two minutes** for a 6–11 MB set. The parse is the slow part,
not the transfer: this runs on a shared CPU, where the same set that takes
15 seconds on a laptop takes about a minute. The bundled designs are
precomputed, which is why they open instantly.

---

## The reviewer's side

Everything the interface uses is addressable, so you can check our work
without taking our word for any of it. No credentials:

| | |
|---|---|
| Interactive API docs | https://ecarbon.fly.dev/docs |
| Bill of quantities | `GET /projects/{id}/takeoff` |
| Carbon result | `GET /projects/{id}/carbon` |
| Where a line came from | `GET /projects/{id}/trace/{line_id}` |
| The sheet, with the region outlined | `GET /projects/{id}/trace/{line_id}/image.png?page=N` |
| Open decisions, priced | `GET /projects/{id}/unspecified` |
| Ranked substitutions | `GET /projects/{id}/substitutions` |
| Correct a quantity, get carbon back | `POST /projects/{id}/lines/{line_id}` |
| Upload a plan set | `POST /projects/upload` (multipart) |

```bash
curl https://ecarbon.fly.dev/projects
curl -F "file=@plans.pdf" https://ecarbon.fly.dev/projects/upload
```

The **Download takeoff** button gives the same bill as CSV, every line with
its sheet, detail, basis and confidence — so a reviewer can check the figures
in their own spreadsheet rather than through our interface.

---

## What the numbers mean, and where they are weak

Everything below is printed by a script in `scripts/`, named beside it in
[docs/benchmark.md](benchmark.md). Worst cases are published next to medians.

| | |
|---|---|
| Opens, across the whole 53-set catalogue | **0 crashes** |
| Element coverage | median **52%**, best **100%** |
| Alberta (the development region) | **100%** on six of seven |
| Window / door counts vs the IFC models | median **4.0%** / **0.0%** |
| Building footprint vs the IFC | median **3.3%** |
| Interior partition run length | median **5.7%**, worst **+92%** |
| Factors | **20**, every one a sourced record; none in code |

**The headline is a best case, not a typical one.** Alberta is the region this
was developed against. The catalogue median is 52%, and a design reaches 80%
only when both its assemblies schedule and its openings schedule are readable.

**Eight of the 53 sets produce nothing at all** — the NOR packages were exported
with their text converted to vector outlines, so there are no readable
dimensions, schedules or sheet titles. They are reported as unreadable rather
than estimated.

**Coverage and correctness are different axes.** Ontario reads 29% where it
once read 42%, and that is a correction: the 13 points it lost were a roof
assembly being read at 75% error. We would rather report less and be right.

**There is no reference takeoff.** CMHC publishes quantity take-offs for these
designs but does not include them in the public data package, so every accuracy
figure above is measured against geometry we derived ourselves from the IFC
models — not against a quantity surveyor's bill.

---

## Scope discipline

Our figure is **A1–A3 only** — product stage. CMHC publishes 162 tonnes for
`AB_Fourplex_01`, but that bundles construction, sixty years of replacement and
demolition. Summing across module scopes is the mistake this challenge tests
for, so the engine **raises** rather than totalling them. Where no factor
exists — the steel screw piles — the line appears, uncounted, with the reason.

---

**6. The massing, in carbon.** Press **Carbon** on "What we understood from
the drawings" to colour every surface by what its element class carries. The
figures sit beside the swatches, because the top two classes are 12,305 and
10,909 kgCO₂e and no one should be asked to separate those by hue.

---

## A note on the drawings

The plan sets bundled here are from the public
[CMHC Housing Design Catalogue](https://www.cmhc-schl.gc.ca/housing-design-catalogue).
They are licence-restricted, which is why the drawings are not in the public
repository.
