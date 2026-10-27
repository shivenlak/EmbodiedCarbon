# Five-minute demo — running order

Submission 1 asks for a video of the front end and the back end. Five minutes
is enough for one complete pass and nothing else, so this shows the loop end to
end rather than touring features.

**Before recording:**

1. The Fly card must be on the account, or the machine stops five minutes
   after each deploy and the link dies mid-take.
2. `fly deploy --remote-only --ha=false`, then `deploy/warm.sh`.
3. Have a plan set on the desktop that is **not** one of the five bundled.
   `AB_Rowhouse_01` is the right choice: it exercises the floor-area
   correction live, where the stated 74 m² is replaced by the 286 m² the
   drawings depict.

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

## 1:50 — What we understood from the drawings

Scroll to the axonometric.

> "This is not a render of a building. It is the takeoff, drawn. The box is
> the footprint we measured off the linework — seven by twenty-two metres.
> The floors sit at the datums we read from the sections. And these
> seventy-three walls are the partitions we counted, standing where we
> counted them.
>
> Which means if we read it wrong, you can see that we read it wrong. On one
> of the ADUs our partition detection over-counts by ninety-two percent, and
> on that building you see walls with no room between them. We would rather
> you could catch us."

Click **Storey 1** and **Storey 2** so the wall sets change.

## 2:20 — Every sheet in the set

> "Forty-six sheets. We opened all of them and classified every page. Four
> carry a quantity in the bill — and two of those four are the schedules,
> which is where every build-up comes from. One sheet had no readable text,
> and it is drawn hatched rather than left out, because a page we could not
> read is a fact about the drawing set, not a gap in our chart."

## 2:40 — Click to trace

Click the `S201` tag on the slab line. The sheet opens framed on the region.

> "Every quantity traces back to the sheet and the detail. It opens zoomed to
> what was read, because a thirty-six by twenty-four inch sheet scaled to fit
> a window is a grey haze."

Then click an **interior partition** line and switch between A101 and A102.

> "This one is a different claim, and we label it differently. These outlines
> *are* the measurement — one rectangle per wall counted, on each storey.
> 'We measured this' and 'we read this from a schedule' are not the same
> thing, so the panel says which."

## 3:05 — Edit a quantity

Change a wall area. Total updates.

> "An estimator disagrees, types their figure, carbon recomputes in nine
> milliseconds. The line is then marked as overridden — their number, our
> arithmetic."

## 3:20 — Decisions still open, then substitutions

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

Press **Upload a plan set** and drag in the set that is **not** bundled.

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
