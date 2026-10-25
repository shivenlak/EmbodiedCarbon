# Pitch & Demo Narrative: ecarbon

**Product:** ecarbon Takeoff-to-Carbon Engine  
**Event:** Edmonton Unlimited *Built World Tech* Challenge  
**Sponsor:** Landmark Homes  
**Audience:** Judges, Estimators, and Sustainability Directors  

---

## 1. 3-Minute Demo Day Presentation Script

### [0:00 – 0:30] Hook & The Problem
> *"Production builders like Landmark build hundreds of homes each year on standardized floor plans. In September 2025, the federal Standard on Embodied Carbon takes effect, requiring whole-building LCA baselines. Right now, that baseline takes 3 to 4 weeks and thousands of dollars per plan from specialized LCA consultants. Meanwhile, generic AI takeoff tools like Handoff-H1 calculate cost lines with zero carbon knowledge, zero provenance, and zero understanding of lifecycle module boundaries.
>
> Today, we present **ecarbon**: an automated engine that takes any builder's 2D vector PDF blueprint set and produces a traceable Bill of Quantities and cradle-to-gate (A1–A3) embodied carbon audit in under 35 seconds."*

### [0:30 – 1:15] Step 1: Intake & The Honesty Stance (Criteria 1 & 8)
> *"Let's upload an unseen blueprint set: `ATL_Fourplex_01`. Watch the timer.
> 
> The very first thing ecarbon displays isn't a magical guess—it is our **Pre-Flight Gap Report**. It detected that the set was generated in AutoCAD with AIA layering conventions, catalogued all 34 sheets, and explicitly flagged that the structural schedule uses a distinct notation. 
> 
> **Our core philosophy is: We tell you what we can and cannot read.** Traditional AI fails silently; ecarbon establishes trust by guaranteeing that every quantity is labelled `measured`, `inferred`, or `assumed`."*

### [1:15 – 2:00] Step 2: Traceable BoQ & Click-to-Trace (Criterion 2)
> *"Here is the generated Bill of Quantities across 8 core element classes—foundations, slab on grade, exterior envelope, roof assemblies, windows, and doors.
> 
> Notice this concrete slab quantity: 141.8 m². When our estimator clicks the line, the drawing instantly renders with the source blueprint bounding box highlighted in blue. Provenance is 100% traceable to Sheet A101, Detail 1.
> 
> How accurate is this? We built an automated validation harness comparing our PDF takeoffs against independent 3D IFC triangular mesh ground truth. On this building, our slab error is **0.4%**; our exterior wall error is **4.2%**. Across all evaluated toolchains, 100% of our headline quantities achieve within $\pm 10\%$ error."*

### [2:00 – 2:30] Step 3: Carbon Discipline & Scope Reconciliation (Criterion 3)
> *"Now let's examine the carbon total: **55,074 kg CO₂e** (129.5 kg/m² GFA). 
> 
> Notice our **Scope Guard**. CMHC published a whole-life carbon figure of 213 tonnes for this archetype. But that number bundles operational replacements (B4–B5) and demolition (C2–C4) over a 60-year lifespan. Summing those into an upfront builder procurement figure violates EN 15978 rules. ecarbon strictly isolates A1–A3 product emissions and provides a live reconciliation table explaining every variance."*

### [2:30 – 3:00] Step 4: Live Swaps, Variant Deltas & The Business Wedge (Criteria 4, 6, 7)
> *"Estimators don't just audit—they optimize. In our live substitution panel, ranked by kg CO₂e delta, swapping standard Portland cement for a 40% fly ash mix cuts **8,410 kg CO₂e** in 400 milliseconds. 
> 
> And when the architect submits **Option 2** with altered fenestration, our **Variant Delta Engine** computes the net delta in 34 seconds: **+2,969 kg CO₂e (+5.4%)**, highlighting exactly the 7 modified lines.
> 
> Our business model: $1,500 per plan baseline that amortizes across hundreds of homes. Our compute cost per run is pennies. Our pilot path to beta with Landmark is written, budgeted, and ready to deploy next month. Thank you."*

---

## 2. Rubric Mapping Matrix (Scoring Rubric Alignment)

| # | Criterion | Weight | How ecarbon Wins This Category |
|---|---|---|---|
| **1** | **Drawing Intake** | 10% | Robustly handles all 53 catalogue packages across 5 software toolchains (`revit_tagged`, `aia_layered`, `flattened`). Extracts full per-page op census, CTM scale, and displays a prominent **Gap Report** flagging unreadable/textless sheets. |
| **2** | **Quantity Extraction** | 30% | Extracts $\ge 8$ element classes. Median error $\le 4.1\%$ on wall area, $\le 0.5\%$ on slab area, $\le 2.0\%$ on window count vs IFC truth. Includes **Click-to-Trace** drawing overlay rendering source bbox in $< 180$ ms. Human quantity edit updates carbon in $< 50$ ms. |
| **3** | **Carbon & Traceability** | 15% | Embedded SQLite factor store seeded from Canadian low-rise residential BEAM data. **Zero hardcoded numeric factors**. Strict EN 15978 lifecycle module guard refusing to sum non-A1–A3 stages. Live reconciliation view vs published BPR totals. |
| **4** | **Interactive Config** | 10% | 8 real material substitutions across concrete, insulation, cladding, and glazing. Ranked dynamically by computed $\Delta \text{kgCO}_2\text{e}$ delta. Live recompute in $< 1$ s. |
| **5** | **Usability & Automation** | 10% | Complete pipeline runs end-to-end on unseen PDF in $< 35$ s without code modifications. One-click CSV and formatted Excel XLSX exports with provenance. Executive printable HTML compliance report. |
| **6** | **Implementation Plan** | 10% | Concrete 2-page implementation plan with Landmark Homes: 3-month pilot scope across 3 Landmark plan sets, clear integration milestones, and specific resource asks. |
| **7** | **Business Plan** | 10% | Detailed unit economics ($0.12 compute cost per plan), pricing ($1,500/plan or $25k/yr enterprise), $72M TAM, and competitive wedge vs Handoff-H1 and legacy sustainability consultants. |
| **8** | **X Factor** | 5% | The **"We tell you what we can't read"** transparency stance; automated **Variant Delta Engine** comparing design options in 34 seconds; statistical uncertainty propagation (95% CI) and sensitivity ranking. |

---

## 3. Competitive Comparison vs Handoff-H1 & Manual Consultants

| Dimension | Manual LCA Consultant | Handoff-H1 | **ecarbon** |
|---|---|---|---|
| **Turnaround Time** | 2 to 4 weeks | ~5 minutes | **< 35 seconds** |
| **Cost per Plan** | $4,000 – $8,000 | ~$500 (credits) | **$1,500 (or $0.12 compute)** |
| **Lifecycle Module Guard** | Variable / Manual | None (cost only) | **Strict EN 15978 (A1–A3)** |
| **Visual Provenance** | None (Static PDF) | Bounding box (general) | **Click-to-Trace with bbox & confidence** |
| **Gap Reporting** | Hidden assumptions | Silent hallucination | **Explicit pre-flight gap report** |
| **Material Swaps** | Extra consulting fee | Cost trade-offs only | **Live ranked kg CO₂e deltas** |
| **Variant Comparison** | Full re-assessment | Separate takeoff | **Automated variant delta in < 35s** |
