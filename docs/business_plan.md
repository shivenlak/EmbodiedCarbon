# Business Plan: Commercial Strategy & Market Expansion

**Product:** ecarbon Takeoff-to-Carbon Engine  
**Author:** Antigravity Team  
**Challenge:** Edmonton Unlimited Built World Tech Challenge  
**Date:** October 2026  

---

## 1. Market Opportunity & Regulatory Forcing Function

Embodied carbon in the built environment accounts for **~11% of global greenhouse gas emissions** and **~50% of the whole-life emissions of high-efficiency new construction**. While operational emissions have been targeted by Canadian building codes (Tiered Energy Codes, BC Step Code, NECB), embodied carbon has historically lacked automated measurement tools.

This is rapidly changing due to aggressive regulatory mandates:
- **Federal Standard on Embodied Carbon in Construction** (Amended March 2025; effective September 2025) requires major federally funded and leased buildings to measure and reduce embodied carbon.
- **Municipal Requirements:** The City of Vancouver and the City of Edmonton require upfront carbon disclosures for rezoning and major developments, with anticipated intensity caps by 2027.
- **Corporate ESG Pressures:** Volume production builders face growing investor, municipal, and homebuyer demand for certified low-carbon homes.

### The Problem: Status Quo Breakdown
Currently, assessing embodied carbon requires hiring external sustainability consultants.
- **Cost:** \$3,000 to \$10,000 per design assessment.
- **Turnaround:** 3 to 6 weeks per plan set.
- **Bottleneck:** Estimating teams must complete a manual takeoff in Excel or PlanSwift, hand it to an external LCA practitioner using One Click LCA or Athena, and wait weeks for a report that arrives too late to influence procurement or design decisions.

---

## 2. Target Customer & Value Proposition

### Ideal Customer Profile (ICP)
- **Target Buyer:** VP of Estimating, Director of Construction Technology, or Sustainability Lead at **production homebuilders** building **100 to 1,000 homes per year** on standardized plan catalogues (e.g., Landmark Homes, Brookfield Residential, Jayman Built, Mattamy Homes).
- **Core Pain Point:** Inability to run rapid "what-if" material substitution analysis during pre-construction without incurring consulting fees and project delays.

### Value Proposition
1. **From Weeks to 90 Seconds:** Upload drawing set PDFs and receive a complete, traceable Bill of Quantities (BoQ) and A1–A3 embodied carbon score in under 2 minutes.
2. **Amortized Plan Economics:** Production builders build dozens or hundreds of units from a single standardized plan. A one-time \$1,500 baseline amortizes to **\$15 per home at 100 units from that plan, and under \$2 at 1,000** — the span of our stated customer profile. The cost is per plan, not per home, which is what makes it affordable at exactly the point a consultant assessment is not.
3. **Traceability & Trust:** Every quantity links directly to the source drawing sheet, detail, and bounding box. No black-box AI hallucinations.
4. **Interactive Material Optimization:** Live substitution simulator, ranked by computed saving rather than listed alphabetically. On our reference design, switching the slab and grade beam from Portland GU 30 MPa to a 40% fly ash mix is **36.6% less carbon per cubic metre of concrete**, which is **7.1% of that building's total**; switching cavity insulation from mineral wool to dense-pack cellulose is a further **12.9%**. We quote both the per-material and the whole-building figure because they differ by a factor of five, and a saving quoted only the first way reads as five times larger than it is.

---

## 3. Business Model & Pricing

We utilize a hybrid model combining per-plan baseline pricing with an enterprise annual subscription:

| Tier | Price | Ideal For | What's Included |
|---|---|---|---|
| **Per-Plan Baseline** | **\$1,500 / plan set** | Mid-size builders, one-off projects | Complete takeoff, A1–A3 carbon audit, substitution engine, exportable compliance report |
| **Annual Enterprise** | **\$32,000 / year** | Volume builders (150–800 homes/yr) | Unlimited plan uploads, custom supplier EPD integration, ERP estimating export, dedicated API |
| **Municipal / Consultant** | **\$48,000 / year** | Municipal permit offices, LCA engineers | Multi-firm review portal, automated wbLCA audit checks, permit compliance verification |

### Willingness to Pay Benchmark
- External LCA consultant: \$4,000–\$8,000 per assessment.
- At 10 plan sets per year, a builder spends **\$50,000+** on consultants with zero workflow integration.
- At \$32,000/year, ecarbon delivers **faster results, continuous re-runs, live material swaps, and a 36% direct cost savings**.

---

## 4. Unit Economics & Compute Cost

Because our architecture relies on deterministic vector parsing, scale calibration, and local EPD factor lookups rather than giant multi-modal foundation models for every operation, marginal compute cost per set is exceptionally low:

| Cost Item | Cost per Plan Set | Notes |
|---|---|---|
| **PDF Ingestion & Vector Parsing** | \$0.02 | PyMuPDF local processing (CPU) |
| **Scale, datum and schedule parsing** | \$0.05 | Deterministic layout parsing, no model call |
| **Factor Store Lookup & Recompute** | \$0.01 | Local SQLite / DuckDB query (< 10 ms) |
| **Cloud Hosting & Storage** | \$0.10 | AWS ECS / Render container allocation |
| **Total Marginal Serving Cost** | **\$0.18** | Per 50-page set, from a measured 13.2 s median / 25.4 s worst on one CPU core |

**Gross Margin:** **> 98%** on per-plan revenue. The cost structure here is
sales, not serving — which is the direct consequence of an architecture that
measures geometry deterministically instead of asking a large model to read
every sheet.  
Customer Acquisition Cost (CAC) is paid back within 2 months of an annual subscription.

---

## 5. Competitive Landscape & Defensible Wedge

| Capability | ecarbon | Handoff-H1 | One Click LCA | Manual Estimating (PlanSwift) |
|---|---|---|---|---|
| **Primary Focus** | **Carbon + Traceable BoQ** | Multi-trade Cost | Heavy Industrial LCA | Cost Takeoff |
| **Drawing Input** | **Vector PDF, uploaded** | PDF / vision agents | Manual entry / BIM | Manual on-screen tracing |
| **Turnaround Time** | **Under 2 min** (13 s median measured) | Not published | Days / Weeks | 2–5 days per set |
| **Module Scope Discipline** | **Strict A1–A3 Enforced** | None | User Configured | None |
| **Click-to-Trace Provenance** | **Yes — sheet, detail, and the region outlined on it** | Partial | None | Manual links |
| **Explicit Gap Reporting** | **Yes ("We tell you what we can't read")** | No | No | No |
| **Interactive Live Swaps** | **Yes (Ranked by kg CO₂e)** | Cost only | Re-run required | Manual spreadsheet edits |

### The Wedge
- Competitors either focus strictly on multi-trade cost estimating (ignoring carbon and traceability) or require complex 3D BIM models that low-rise residential builders rarely maintain. **Handoff-H1 is the serious comparison** and we take its published numbers seriously: 81.6% composite against 77.6% for professional human estimators, with 78.8% of quantities inside ±25%. It does multi-trade cost takeoff with no carbon layer, no module-scope discipline and no gap reporting. We are not claiming to extract better than they do; we are claiming the carbon layer, the traceability and the refusal to guess, which is a different product.
- **ecarbon owns the vector PDF to carbon bridge.** Once a builder adopts ecarbon for carbon compliance, the underlying BoQ is an immediate springboard into automated material cost estimating, unlocking a **\$12B+ global pre-construction estimating software market**.
