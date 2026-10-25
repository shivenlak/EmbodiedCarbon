# Implementation Plan: Pilot Path to Beta with Landmark Homes

**Author:** Antigravity Team  
**Scope:** Automated Blueprint Takeoff to Traceable A1–A3 Embodied Carbon Pipeline  
**Target Partner:** Landmark Homes (Edmonton, AB)  
**Date:** October 2026  

---

## 1. Executive Summary & Objective

Landmark Homes is a pioneer in industrialized, sustainable low-rise residential construction in Alberta. However, estimating upfront embodied carbon (A1–A3) currently requires either weeks of manual quantity takeoff or expensive external lifecycle assessment (LCA) consultants.

**The Pilot Goal:** Deliver a streamlined 6-week beta implementation with Landmark Homes to prove automated blueprint extraction and carbon estimation directly on Landmark's production drawing sets, achieving:
1. **Median takeoff accuracy $\le 10\%$** against Landmark's internal reference estimates.
2. **End-to-end processing time $< 2$ minutes** per plan set.
3. **Immediate payback** by establishing a repeatable, reusable carbon baseline for each standardized model.

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
  - Slab on grade & footings ($m^3$)
  - Foundation walls ($m^3$)
  - Exterior wall assembly areas ($m^2$)
  - Roof assemblies ($m^2$)
  - Floor assemblies ($m^2$)
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

1. **Input Stage:** Landmark drops drawing set PDFs into the web interface or API endpoint (`POST /projects/upload`). No CAD plugins or custom model tagging required.
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

The pilot will be deemed successful and ready for full enterprise adoption upon meeting these measurable gates:

1. **Extraction Accuracy:** $\ge 85\%$ of all element quantities within $\pm 10\%$ of Landmark's reference takeoff, with median error $\le 6\%$.
2. **Speed:** End-to-end takeoff and carbon estimation completed in $< 120$ seconds per plan set.
3. **Auditability:** $100\%$ of generated quantities carry sheet number and detail provenance.
4. **Traceable Zero-Jargon Output:** Estimator and sustainability lead can explain every line in the final embodied carbon total without consulting external LCA manuals.
