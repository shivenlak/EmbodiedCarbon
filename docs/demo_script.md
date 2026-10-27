# Five-minute demo — running order

Submission 1 asks for a video of the front end and the back end. Five minutes
is enough for one complete pass and nothing else, so this shows the loop end to
end rather than touring features.

**Before recording:** redeploy and run `deploy/warm.sh`. The cache lives in the
machine's memory, so a cold design takes 20–200 seconds and a warm one takes
half a second. Have a plan set ready on the desktop that is **not** one of the
five bundled — `AB_Rowhouse_01` is a good choice, because it exercises the
floor-area correction live.

---

## 0:00 — The problem, in one breath

> "A builder wants to know the embodied carbon of a plan set. Today that means
> a manual takeoff in Excel, handed to an LCA consultant, and a report weeks
> later — too late to change anything. This takes the PDF."

Open https://ecarbon.fly.dev. Sign in on camera: it is credentialed because it
reads licence-restricted drawings.

## 0:30 — Lead with what we could not read

Do **not** scroll to the total. Stay on *"What we could not read."*

> "Nineteen notices, before any number. The drawings say 'cladding placeholder'
> — CMHC deliberately leaves it unspecified, so we don't pick one. This design
> numbers its two accessibility options A101 and A102; read both and you count
> that floor twice. And four partition-measurement approaches that failed
> before the fifth worked — published, because if you are deciding whether to
> trust the least certain line, you should know it was hard to get."

This is the differentiator. Nobody else opens with their own limitations.

## 1:15 — The number, given twice

> "48,613 kgCO₂e. And 37,536 without the interior partitions, because that one
> run is measured off the linework rather than read from a schedule — the least
> certain quantity here. A1–A3 only, product stage, and the scope sits inside
> the number."

Point at the coverage bar: **100% of the building by element**.

> "On a design where we only reach 53%, the interface says so before you read
> the total."

## 2:00 — Click to trace

Click the `S201` tag on the slab line.

> "Every quantity is traceable back to the sheet and the detail. This is the
> schedule row the 130 mm came from."

Then click an **interior partition** line and change the page.

> "This one is different — these outlines *are* the measurement. One rectangle
> per wall counted, on each storey. We label how strong the trace is, because
> 'we measured this' and 'we read this' are not the same claim."

## 2:45 — Edit a quantity

Change a wall area. Total updates.

> "An estimator disagrees, types their figure, carbon recomputes in nine
> milliseconds. The line is then marked as overridden — their number, our
> arithmetic."

## 3:15 — Decisions still open, then substitutions

> "Cladding and roofing carry no carbon at all, because the drawings don't
> specify them. We price the range — 1,980 to 3,774 for cladding — and hand the
> decision back rather than defaulting one and saying nothing."

Scroll to substitutions.

> "Ranked by what they actually save, computed against these quantities.
> Cellulose for mineral wool is 12.9% of the total. The fly-ash concrete mix is
> 36.6% less carbon per cubic metre, which is 7.1% here — we quote both,
> because quoted only the first way it reads five times larger than it is."

## 4:00 — The back end

Open https://ecarbon.fly.dev/docs on camera.

> "Same credentials. Every endpoint the interface uses is here — the bill of
> quantities, the carbon result, the trace with its bounding boxes, the
> overrides. The interface is a client, not the product."

Show one `curl` with the quantity override or the trace JSON.

## 4:30 — Upload something it has never seen

Drag in the plan set that is **not** bundled.

> "Nothing here is specialised to the designs we shipped. Same gap report, same
> bill, same traceability — on a set this service has never opened."

Let it finish on camera if it fits (about 20 seconds); otherwise cut to the
result.

> "Which is the only test that counts, because the sets that matter are
> Landmark's, and we have never seen those either."

## 4:50 — Close

> "Zero crashes across all 53 catalogue sets. Median element coverage 52%,
> 100% on the region we developed against. Door counts exact against the
> reference models. And the published benchmark includes the worst cases and
> the regressions, because a benchmark that only reports its wins is not a
> benchmark."

---

## If something goes wrong on camera

- **"The reader is not running"** → the service is up but unauthenticated.
  Sign in again; sessionStorage was likely cleared.
- **A design takes 20+ seconds** → the machine restarted and lost its cache.
  Run `deploy/warm.sh` and re-record.
- **502 on a big design** → Fly's proxy timed out a cold build. Warm first;
  warming runs inside the machine specifically to avoid this.

## What not to claim

- Do not call the catalogue median "accuracy" — it is element coverage.
- Do not compare our A1–A3 figure to CMHC's published whole-life total without
  saying the module scopes differ. The engine refuses to sum them; the demo
  should not blur them either.
- Do not say "every province works." Eight sets produce nothing, and the
  benchmark says so.
