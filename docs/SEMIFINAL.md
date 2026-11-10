# Semifinal runbook

A live demo to judges, scored on the rubric below. This replaces
`demo_script.md` for the semifinal. That script was written for a recorded
video and for Submission 1, before the scenario builder existed.

Every figure here was read off the live API on 10 November. If the screen says
something different, **say what the screen says**.

---

## The rubric, and the screen that answers each line

| # | Criterion | Weight | Show this | One line to say |
|---|---|---|---|---|
| 2 | Quantity extraction | **30%** | Bill of quantities: sheet tag → trace. Then correct a quantity. | "Every number names its sheet and says whether we measured it, inferred it, or assumed it." |
| 3 | Carbon and traceability | 15% | Bill: the factor line under each kgCO₂e, and the derivation | "Quantity times factor, and the factor's source, region and module scope are on the line." |
| 1 | Drawing intake | 10% | Review notes: the sheet strip, then the notes | "It opened 46 sheets, classified every one, and told us what the drawings leave open." |
| 4 | Interactive configuration | 10% | Options: apply swaps, make the cladding and roofing decisions | "Ranked by kilograms saved, and the total moves as you choose." |
| 5 | Usability and automation | 10% | Switch to Sixplex. Upload a set. Download the CSV. | "Nothing is tuned to one building, and the output is a spreadsheet an estimator already uses." |
| 6 | Implementation plan | 10% | Talk, no screen | Six-week Landmark pilot (below) |
| 7 | Business plan | 10% | Talk, no screen | $1,500 a plan, $32k a year; about $0.18 to serve (below) |
| 9 | X factor | 5% | The review notes and the "twice" total | "It refuses to guess, and it tells you where." |

Quantity extraction is 30% on its own, so spend the most time there.

---

## Before you walk in (T−60 min)

1. **Open https://ecarbon.fly.dev/?plan=AB_Fourplex_01**, press **Continue as
   a guest** (or sign in), and check the headline reads **43,075**.
2. **Warm it.** Run `deploy/warm.sh`. Without the warm, the first sheet-tag
   press takes about 16 s instead of 0.2 s. Then press one sheet tag yourself
   to confirm it's fast.
3. **Open these tabs, in this order:**
   - `https://ecarbon.fly.dev/?plan=AB_Fourplex_01` (the showcase)
   - `https://ecarbon.fly.dev/?plan=AB_Fourplex_01#quantities`
   - `https://ecarbon.fly.dev/?plan=AB_Fourplex_01&trace=ln-interior-partition-p1-l0` (backup for the money shot)
   - `https://ecarbon.fly.dev/?plan=AB_Fourplex_01#options`
4. **Put an upload file on the desktop:** `AB_Rowhouse_02_Drawings.pdf` from
   `~/ec-data/cmhc/AB_Rowhouse_02_Technical_Design_Package/`. It's a set the
   app does not bundle.
5. **Backup if the venue Wi-Fi dies:** run it locally, which gives the same
   app on the same data.
   ```bash
   cd web && npx vite build --logLevel error && cd ..
   EC_DATA="$PWD/deploy/data" .venv/bin/python -m uvicorn ecarbon.api.main:app --port 8000
   # then open http://localhost:8000/?plan=AB_Fourplex_01
   ```
   Check that nothing else holds port 8000 first (`lsof -i :8000`). An old
   server from 27 October was still running there and served pre-fix numbers
   (48,613).
6. Zoom the browser to about **125%** if the room uses a projector.

**Corrections are private to your workspace.** A correction you make on stage
is seen by you alone, not by a judge on their own laptop, so there is nothing
to clean up. Press **undo** anyway, to show the figure goes back to 43,075.
If a rehearsal left your workspace messy, press **Leave** (top right) and
**Continue as a guest** for a fresh one.

> "Every visitor works in their own workspace: a correction or an upload is
> yours, and nobody else sees it. Sign in and it's kept under your name."


---

## The demo, about six minutes

### 0:00 The problem (20 s)

> "A production builder wants the embodied carbon of a plan. Today that means a
> manual takeoff, handed to an LCA consultant, and a report three to six weeks
> later, after the spec is locked. This reads the PDF plan set directly, in
> about a minute."

### 0:20 The model (40 s): *quantity extraction*

Tab 1 opens on the **showcase**. Let it play: the rendering from the plan
set's cover appears, steps back, and the measured model rises from the slab,
floor plan first.

> "That's the building as its architect drew it, from the cover of the PDF.
> And this is what we read off the other forty-five pages."

Drag to orbit, over the top and underneath to the grade beam. Pull the
**Explode** slider to open the storeys. Hover a wall: it says what it is and
its carbon per m². Swipe the panel on the right to **Carbon** and the model
turns into a heat map.

The bill, the review notes and the options open as a sheet over the model:
press "All 20 lines", "Every note" or "All 14 swaps" at the bottom of a panel,
or open the `#quantities`, `#gaps` and `#options` links directly. **Back to
the model** (or Esc) closes the sheet.

> "This is the takeoff, drawn. The footprint is 7 by 22 metres, measured off
> the linework. The two storeys are at the datums read from the sections, and
> these are seventy-three partition walls counted on the plans. Every surface
> is a quantity in the bill, so if we misread something you'd see a wrong
> shape, not just a wrong number."

Point at the right panel:

> "43,075 kilograms CO₂e, product stage A1 to A3, 140.8 per square metre. And
> it's given twice: 37,536 without the interior partitions, because that's the
> one quantity we measure off linework instead of reading from a schedule. It's
> the least certain thing here, so you get both numbers."

### 1:00 Show your work (90 s): *quantity extraction, traceability*

**Press "Interior partitions · A003"** in the panel, or open tab 3.

> "Press any number and the sheet it came from opens. Each outlined rectangle
> here *is* the measurement: one wall whose length is in the total. The badge
> says how strong the trace is. 'Measured here' means the outline is the
> measurement. 'Read from this' means a schedule row. 'Sheet only' means we know
> the sheet but not the spot, so we highlight nothing rather than point at a
> guess."

Close. Go to **Bill of quantities** (tab 2).

> "Twenty lines off a forty-six page set. Each has its quantity, its basis
> (measured, inferred, or assumed), the sheet, and the carbon."

Point at the small line under **5,526**: `× 276 /m³ · Kootenay · CA-AB · A1–A2–A3`.

> "And here's how the carbon was made: 20.02 cubic metres of concrete times
> 276 kilograms per cubic metre. The factor is from the Kootenay guide,
> Alberta-specific, product stage only."

Press **how this was derived** on the slab:

> "Footprint measured off the linework and confirmed against the dimension
> strings to 0.0%. Thickness stated on the drawing. Factor, source, region,
> module, and its ±15% uncertainty."

**Correct a quantity.** Press **20.02**, type **25**, Enter.

> "If an estimator disagrees, they correct it. The carbon recomputes straight
> away, and our reading stays beside theirs, so the correction is visible."

**Press undo.** Headline back to 43,075.

### 2:30 What it doesn't know (60 s): *intake, honesty*

**Review notes.**

> "Nineteen notes on this set. These aren't errors. They're the places where
> the drawings leave something open. The cladding is drawn as a placeholder,
> so we don't assign it a material. Two sheets are alternative versions of the
> same floor, so we count one, because counting both would double the windows."

Scroll to the sheet strip:

> "All forty-six sheets, classified: schedules, plans, sections, cover pages.
> The dark ones are the four the bill rests on. One page has no readable text,
> and it says so."

> "A low total that doesn't say it's partial looks exactly like a good one.
> So this tool says so."

### 3:30 Configure it (75 s): *interactive configuration*

**Options** (tab 4).

> "Two decisions are still open. The drawings literally say 'cladding
> placeholder' and 'roofing placeholder'. So we don't pick one; we price the
> range and hand the choice back."

**Press Vinyl Siding** (+1,980) and **Asphalt Shingles** (+1,371). Watch "Your
specification" climb.

> "Now the builder makes the call, and the total follows."

**Press Apply on #1** (slab insulation XPS → EPS, −3,277) and **#4** (slab
concrete, 40% fly ash, −2,022).

> "Substitutions, ranked by kilograms actually saved on this building, not
> listed alphabetically. Apply two and we're under the drawings' figure, even
> with cladding and roofing now counted."

Point at the italic caveat under the insulation swap:

> "And note it tells you this insulation swap is at the same thickness and not
> matched for R-value. We'd rather say that than let you find out at the code
> review."

Optional: press **#6** (25% fly ash on the same slab). It *replaces* #4 rather
than stacking: "two mixes for one slab are alternatives, so it never
double-counts."

Press **Reset**.

### 4:45 Not just one building (45 s): *usability, range*

Switch the project selector to **AB Sixplex**.

> "Three storeys, six units, 69,462 kilograms, 105.8 per square metre."

Point at the amber line under the stats ("Floor area measured from the
drawings — whole block, confirm this"). The full note is the red **Read this
first** at the top of Review notes.

> "And it flags this: the project states 492 square metres, but the drawings
> show 656. The stated figure covers less than what's drawn. We don't invent a
> multiplier. We say which area we used, and ask you to confirm it."

Optional: **Upload a plan set** with `AB_Rowhouse_02_Drawings.pdf`. Start it,
keep talking, and come back to it. It's a 10 MB set the app has never seen.

**Download CSV:**

> "Every line, with its sheet, basis and confidence, in the spreadsheet your
> estimator already uses."

### 5:30 Close (30 s): *implementation, business*

> "Landmark is the first pilot: six weeks on three of your plan sets, scored
> line by line against your estimators' own takeoffs. $1,500 a plan set,
> which at 100 homes off one plan is $15 a home, or $32,000 a year for a
> volume builder. Serving cost is about eighteen cents a set, because it's
> deterministic vector parsing, not a language model reading every sheet."

---

## Figures to have in your head

| | |
|---|---|
| AB_Fourplex_01 total | **43,075** kgCO₂e A1–A3 |
| without inferred partitions | **37,536** |
| intensity | **140.8** kg/m² gross, over **306** m² |
| bill | **20** lines from **46** sheets (45 with readable text) |
| review notes | **19** |
| partitions | **73** walls |
| slab | 20.02 m³ × 276 kgCO₂e/m³ = **5,526** |
| cladding (open) | 1,980–3,774 |
| roofing (open) | 1,371–2,433 |
| top swap | slab XPS → EPS, **−3,277** (−7.6%) |
| AB_Fourplex_02 | 64,894 · 107.3 kg/m² |
| AB_Sixplex | 69,462 · 105.8 kg/m² · 656 m² |
| catalogue | **53** sets, **0** crashes; **8** text-as-outlines sets refused |
| footprint vs IFC | median **3.3%** |
| doors / windows vs IFC | median **0.0%** / **4.0%** |
| partitions vs IFC | median **5.7%**, worst **+92%** |
| coverage | Alberta **100%** on six of seven; catalogue median **52%** |
| factors | **20**, each a sourced record (Kootenay, BEAM, EC3, Gypsum Association) |

---

## Questions judges are likely to ask

**"How accurate is it against a real takeoff?"**
CMHC doesn't publish its quantity takeoffs in the data package, so there's no
quantity-surveyor bill to score against. We scored against geometry from the
IFC models that ship with the catalogue: footprint 3.3% median, doors 0.0%,
windows 4.0%, partitions 5.7% median with a worst case of +92%, and we publish
the worst cases. The pilot fixes this: week one scores us against Landmark's
own estimators.

**"Why is the cladding zero?"**
Because the drawing says "placeholder". Choosing one silently would move about
5–9% of the total on an assumption nobody made. We price the range and let the
builder decide, on the Options page.

**"Is the XPS to EPS swap fair? EPS has a lower R-value."**
It's priced at the same thickness, and the card says so. Matching for R-value
means a thicker EPS layer and a smaller saving. That's a known limitation, and
it's flagged on screen.

**"Why A1–A3 only? CMHC says 162 tonnes for this building."**
CMHC's 162 t bundles construction, sixty years of replacement and demolition.
Adding stages together is the mistake this challenge tests for, so the engine
raises an error rather than mixing module scopes.

**"Does it use AI? Could it hallucinate?"**
No language model in the pipeline. It reads the vector geometry and text
directly from the PDF: linework, dimension strings, schedules, section datums.
That's why it's traceable, why it's cheap to serve, and why a misread shows up
as a wrong shape rather than a confident wrong number.

**"Will it work on our drawings?"**
Any vector PDF exported from Revit or AutoCAD. A scanned or raster PDF won't
work, and neither will a PDF whose text was converted to outlines (eight
catalogue sets are like that). It reports those as unreadable and produces
nothing, rather than estimating.

**"How long on a new set?"**
About 20 s to a couple of minutes on the server for a 6–11 MB set; 6–25 s on a
laptop. Bundled sets are precomputed and open instantly.

**"What if your quantity is wrong?"**
Correct it in the bill; the carbon recomputes and our reading stays beside
yours. Or press the sheet tag and check the outlined region yourself.

**"Where do the factors come from?"**
Twenty factors, each a sourced record with declared unit, region, module scope,
data type and stated uncertainty: the Kootenay Construction Material Impact
Guide, BEAM, Building Transparency EC3, and the Gypsum Association EPD. They're
shown on every line of the bill. None are hard-coded.

**"Why is the total shown twice?"**
Interior partitions are the one quantity measured off linework instead of read
from a schedule, and they're the least certain. 43,075 includes them; 37,536
doesn't.

**"Who buys this, and why not One Click LCA?"**
The VP of Estimating at a production builder doing 100–1,000 homes a year on
standard plans. One Click needs a BIM model or manual quantity entry, and
low-rise builders work from PDFs. Handoff does cost takeoff with no carbon
layer, no module discipline and no gap report.

**"Can it scale?"**
Stateless API, one deterministic parse per plan set, about $0.18 of compute.
Everything the interface shows is a documented endpoint (`/docs`), so it plugs
into an estimating system rather than replacing it.

---

## If something breaks

| Symptom | Do this |
|---|---|
| Sheet tag takes 15 s+ | Not warmed. Keep talking; it caches after the first press. Run `deploy/warm.sh`. |
| Page blank or "offline" | Switch to the local backup (step 5 above). |
| Headline isn't 43,075 | You left a correction in your workspace. Bill → the blue quantity → **undo**, or **Leave** and start a fresh guest workspace. |
| Upload is slow | Say "it's parsing 46 sheets", carry on with the demo, and come back to it. |
