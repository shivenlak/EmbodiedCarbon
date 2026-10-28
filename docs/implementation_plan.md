# Implementation Plan: Pilot Path to Beta with Landmark Homes

**Author:** Antigravity Team  
**Scope:** Automated Blueprint Takeoff to Traceable A1–A3 Embodied Carbon Pipeline  
**Target Partner:** Landmark Homes (Edmonton, AB)  
**Date:** October 2026  

---

## 1. Executive Summary & Objective

Landmark Homes is a pioneer in industrialized, sustainable low-rise residential construction in Alberta. However, estimating upfront embodied carbon (A1–A3) currently requires either weeks of manual quantity takeoff or expensive external lifecycle assessment (LCA) consultants.

**The Pilot Goal:** Deliver a streamlined 6-week beta implementation with Landmark Homes to prove automated blueprint extraction and carbon estimation directly on Landmark's production drawing sets, achieving:
1. **Median takeoff accuracy within 10%** on the headline quantities, against Landmark's internal reference estimates, with at least 75% of all quantities inside ±25% — the band the best published system reaches (see section 5).
2. **End-to-end processing time under 2 minutes** per plan set, with no code changes for an unseen set.
3. **Every number traceable**: each quantity carries its sheet, detail and confidence, and nothing the drawings leave unspecified is silently defaulted.
4. **Immediate payback** by establishing a repeatable, reusable carbon baseline for each standardized model — the cost is per plan, not per home, so it amortises across every unit built from it.

---

## 2. Pilot Scope & Phased Timeline

```
Week 1: Onboarding & Calibration
   │  - Intake 3 standardized Landmark plan sets (PDF)
   │  - Ingest Landmark's preferred supplier material specifications
   ▼
Week 2–3: Pipeline Calibration & Gap Reconciliation
   │  - Calibrate scale, layer conventions, and detail callouts
   │  - Run automated takeoff and compare with reference estimating sheets
   ▼
Week 4: Beta Deployment & Estimator Shadowing
   │  - Deploy local/cloud interface for Landmark estimating team
   │  - Live substitution testing (low-carbon concrete, alternative insulations)
   ▼
Week 5: Pilot Evaluation & Accuracy Sign-Off
   │  - Measure takeoff error across headline elements (concrete, framing, envelope)
   │  - Generate municipal compliance-ready wbLCA report
   ▼
Week 6: Commercial Rollout & Expansion Roadmap
```

### Phase Details

### Phase 1: Intake & Calibration (Weeks 1–2)
- **Data Ingestion:** Landmark provides vector PDF drawings for 3 representative models (e.g., single-family detached, laneway suite / garage suite, and multi-unit townhouse).
- **Material Factor Mapping:** Map Landmark's specific regional suppliers (e.g., Lafarge ECOPact concrete mix designs, local SPF lumber, specific triple-pane window specs) into our SQLite/local factor store with regional EPD numbers.
- **Drawing Toolchain Alignment:** Tune page classification ladder and viewport scale calibration to Landmark's Revit/AutoCAD drafting standards.

### Phase 2: Pilot Validation & Shadowing (Weeks 3–4)
- **Side-by-Side Comparison:** Run our automated takeoff pipeline concurrently with Landmark's estimating team on 3 live production projects.
- **Accuracy Benchmarking:** Compare quantities across the 8 primary element classes:
  - Slab on grade & footings (m³)
  - Foundation walls (m³)
  - Exterior wall assembly areas (m²)
  - Roof assemblies (m²)
  - Floor assemblies (m²)
  - Window & door schedules (counts and areas)
- **Interactive Substitution Review:** Engage Landmark sustainability and procurement leads to test material substitutions (e.g., Portland GU vs GUL 40% fly ash concrete, cellulose vs mineral wool insulation).

### Phase 3: Workflow Integration & Sign-off (Weeks 5–6)
- **Estimating Workflow Hand-off:** Integrate export pipelines directly with Landmark's ERP / cost estimating spreadsheets via formatted Excel/CSV exports with line-item provenance.
- **Deliverable:** 2-week pilot accuracy and ROI report delivered to Landmark executive team.

---

## 3. Integration Points

Our pipeline connects non-intrusively into Landmark's existing workflow:

```
[ Landmark Architecture ]
           │
     (Vector PDF)
           ▼
[ ecarbon Intake & Takeoff Engine ] ──► [ Factor Store (EPD / Regional DB) ]
           │
           ├──────────────────────────────┐
           ▼                              ▼
[ Interactive Web UI ]         [ Traceable BoQ Export ]
  - Live Carbon Dashboard        - Excel / CSV with Sheet & BBox
  - Ranked Material Swaps        - Municipal Building Permit Package
  - Gap & Unreadability Report   - ERP / Cost Estimating Import
```

1. **Input Stage:** Landmark drops drawing set PDFs into the web interface or API endpoint (`POST /projects/upload`, multipart, vector PDF). No CAD plugins or custom model tagging required.
2. **Review Stage:** Estimators inspect the **Gap Report** first, verifying sheet readability and flagged assumptions before reviewing quantities.
3. **Traceability Stage:** Estimators use **Click-to-Trace** to jump directly to the sheet, detail, and bounding box for any quantity in question.
4. **Output Stage:** One-click export to CSV/XLSX for incorporation into Landmark's cost estimating and procurement systems, plus an exportable report formatted for municipal permit submission.

---

## 4. Resource Commitments & Named Asks

To achieve full beta validation with minimum burden on Landmark's team, we define explicit asks:

| Resource | Landmark Commitment | Our Responsibility |
|---|---|---|
| **Drawing Sets** | 3 representative production plan sets in vector PDF format | Absolute data privacy; files remain local/ephemeral and are never shared |
| **Reference Estimates** | Historic Class B or Class A takeoffs for the 3 selected designs | Benchmark comparison and discrepancy reconciliation |
| **Estimator Time** | 1 senior estimator for **2 hours per week** for 4 weeks (8 hours total) | Preparation of agenda, structured side-by-side walk-throughs, zero busywork |
| **Material Specs** | List of top 10 materials and current suppliers / concrete mix designs | Sourcing verified EPDs and populating local factor snapshot |

---

## 5. Success Criteria & KPIs

These are the gates we would sign, set against what we measure today and
against what the field achieves — not against what sounds best in a proposal.

| # | Gate | Where the number comes from |
|---|---|---|
| 1 | **Median error within 10%** on the headline quantities (slab and footing volume, exterior wall area, roof area, window and door counts) | We measure footprint at 3.3% median, doors at 0.0%, windows at 4.0% against the catalogue's own IFC models |
| 2 | **At least 75% of all quantities within ±25%** of Landmark's reference takeoff | Handoff-H1, a funded purpose-built system, reports 78.8% at this band; professional human estimators reach 87.9%, and *disagree with each other* |
| 3 | **Every quantity carries its sheet, detail and confidence label**, and 90%+ resolve to a highlighted region | 100% carry provenance today; 19 of 20 resolve to a region on the reference design |
| 4 | **Under 120 seconds** per plan set, end to end, no code changes | Catalogue median is 13.2 s, worst 25.4 s |
| 5 | **Zero silent substitutions.** Every material we could not read appears as a gap or a priced open decision, never as a default | Enforced by test; the placeholder-cladding default is specifically guarded against |

**Why gate 2 is not "85% within ±10%".** An earlier draft of this plan
promised that. It is not a target we could meet or that anyone has met: the
best published system reports 78.8% within the much wider ±25% band, and the
human estimators it was benchmarked against hit 87.9% precision while still
disagreeing with one another on the same drawings. A reference takeoff is not
a single right answer. Promising a builder a tighter band than the industry's
best, against a benchmark that is itself uncertain, would make the pilot fail
on arrival — and gates we cannot meet are worse than gates set honestly.

---

## 6. Risks We Already Know About

From building against 53 public sets. These are the things most likely to
cost pilot time, so they are named before the pilot rather than discovered in
week three.

| Risk | What we saw | Mitigation |
|---|---|---|
| **Per-unit vs whole-block floor area** | One catalogue design reports area for a single unit while its drawings depict the whole block, giving an intensity six times its neighbours'. Quantities were right; the denominator was wrong | The upload asks for gross floor area and its basis rather than inferring it. Week 1 confirms the basis against Landmark's own convention |
| **Deferred specifications** | CMHC's drawings say "cladding placeholder" and "roofing placeholder", worth ~12% of a home's embodied carbon | Reported as open decisions priced as a range, never defaulted. Landmark's actual spec closes them in week 1 |
| **Drawing conventions shift inside one PDF** | Architectural pages are Revit exports, structural pages AutoCAD, in the same file. Per-file assumptions break | Detection is per page, not per file |
| **Structural members deferred to another discipline** | Schedules say "see structural", so framing is absent from the architectural set | Reported as a gap. If Landmark's structural sets are available, they are ingested too |
| **A region can regress when another improves** | Every extraction module is shared; a change made for one province moves another. Ontario fell 42% to 29% while Alberta rose to 100% | A pinned regression gate on the development region, run on every change. Landmark's sets get the same treatment from week 2 |

---

## 7. What We Need Before Week 1

Nothing in section 4 is unusual, but two items gate the rest and are worth
confirming early:

1. **The floor-area convention Landmark estimates against** — gross, net, or
   per unit — because it sets every intensity figure the pilot reports.
2. **Whether reference takeoffs exist for the chosen models.** If they do not,
   gate 2 cannot be scored and we would agree a different gate in week 1
   rather than discover it at sign-off. We hit this ourselves: CMHC publishes
   quantity take-offs for these designs and they are not in the public data
   package, so every accuracy figure we report is measured against geometry
   derived from the IFC models instead of against a quantity surveyor's bill.
