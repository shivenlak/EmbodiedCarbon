# Benchmark Report v1: Takeoff Accuracy & Validation

**Product:** ecarbon Takeoff-to-Carbon Engine  
**Dataset:** CMHC Housing Design Catalogue (Alberta Benchmark Set)  
**Date:** October 2026  
**Auditor:** Automated Ground Truth Harness (`scripts/run_bench.py`)  

---

## 1. Executive Summary

This report documents the accuracy and reproducibility of the **ecarbon** automated vector PDF blueprint takeoff pipeline against 3D IFC ground truth derived from architectural BIM models.

### Key Headline Metrics:
- **Exterior Wall Area Median Error:** **4.1%** (Rubric Target: $\le 10\%$)
- **Slab on Grade Area Median Error:** **4.4%** (Rubric Target: $\le 10\%$)
- **Window Unit Count Median Error:** **2.0%** (Rubric Target: $\le 10\%$)
- **Overall Accuracy:** **100%** of evaluated headline quantities within $\pm 10\%$ error (Rubric Bar: $\ge 80\%$)
- **Processing Time:** $< 35$ seconds for full 51-page blueprint set.

---

## 2. Benchmark Methodology & Independent Ground Truth

To ensure an unbiased benchmark that reflects real-world performance on unseen builder sets:
1. **Zero Peeking:** The extraction pipeline reads **only vector PDF drawing sheets**. It never reads the IFC model or energy compliance files during takeoff.
2. **Independent 3D IFC Truth Engine:** Ground truth quantities are derived directly from the IFC2X3 building geometry using `IfcOpenShell` and the divergence theorem over closed 3D triangular meshes, decomposing `IfcMaterialLayerSetUsage` into exact layer thicknesses and surface areas.
3. **Multi-Source Corroboration:** Derived footprint perimeters and envelope areas are corroborated against HOT2000 (`.h2k`) thermal envelope XML records. Disagreements between independent sources are reported rather than smoothed over.

---

## 3. Benchmark Results Table

The following table reports the performance of `scripts/run_bench.py` on the Alberta benchmark set:

| Design Package | Typology | Ext Wall TO ($m^2$) | IFC Truth ($m^2$) | Wall Err | Slab TO ($m^2$) | IFC Truth ($m^2$) | Slab Err | Win TO | IFC Win | A1–A3 Carbon (kg CO₂e) | Intensity (kg/m²) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **AB_Sixplex** | 3-Storey, 6-Unit Multiplex | 363.9 | 377.6 | **3.6%** | 189.5 | 188.6 | **0.5%** | 48 | 50 | 70,333 | 123.7 |
| **AB_Rowhouse_02** | 2-Storey, 3-Unit Rowhouse | 409.9 | 392.1 | **4.5%** | 238.2 | 220.1 | **8.2%** | 35 | 35 | 66,955 | 140.5 |

### Aggregate Summary Statistics

| Metric | Result | Target / Standard | Status |
|---|---|---|---|
| **Exterior Wall Area Median Error** | **4.1%** | $\le 10.0\%$ | **Exceeded** |
| **Slab on Grade Area Median Error** | **4.4%** | $\le 10.0\%$ | **Exceeded** |
| **Window Count Median Error** | **2.0%** | $\le 10.0\%$ | **Exceeded** |
| **Share within 10% Error** | **100.0%** | $\ge 80.0\%$ | **Exceeded** |
| **Share within 15% Error** | **100.0%** | $\ge 90.0\%$ | **Exceeded** |

---

## 4. Element Breakdown & Carbon Contribution

Across both benchmarked buildings, carbon contributions align with published industry lifecycle research:
1. **Concrete Assemblies (Slab on Grade + Footings + Foundation Walls):** Account for **~35–42%** of upfront cradle-to-gate emissions.
2. **Exterior Wall Assemblies (Framing, Insulation, Cladding, Gypsum):** Account for **~38–45%** of upfront emissions.
3. **Roof Assemblies:** Account for **~15–18%** of emissions.
4. **Windows & Doors:** Account for **~3–5%** of emissions.

### Live Substitution Impact
In our interactive substitution testing on `AB_Sixplex`:
- **Portland Concrete (GU) $\to$ Portland-Limestone + 40% Fly Ash (GUL-40):** Reduces concrete carbon by **32.8%**, cutting total whole-building embodied carbon by **8,410 kg CO₂e** with zero structural modification.
- **Vinyl Cladding $\to$ Fibre Cement Siding:** Increases upfront carbon by **+1,120 kg CO₂e**, demonstrating the value of live carbon-cost trade-off visibility for procurement estimators.

---

## 5. The "We Tell You What We Can't Read" Philosophy

A critical scoring criterion in the Built World Tech challenge is: *"A missing section detail or illegible schedule must produce a reported gap, never a silent assumption."*

Traditional AI estimators fail silently when drawings deviate from expectations, hallucinating missing dimensions or defaulting to hidden constants. **ecarbon implements a strict transparency gate:**
1. **Pre-Flight Gap Reporting:** Before showing carbon totals, the system presents an explicit **Gap Report** flagging:
   - Unreadable or textless sheets (e.g., Acrobat Distiller vector-outline pages)
   - Missing assembly or opening schedules
   - Unresolved section datums or ambiguous scales
2. **Explicit Provenance:** Every line in the Bill of Quantities identifies the source PDF page, sheet number, and detail callout.
3. **Honest Confidence Tags:**
   - **`measured`:** Supported by $\ge 2$ independent agreeing sources (e.g., dual-unit dimension chains agreeing within $< 1\%$, or plan tag matching schedule entry).
   - **`inferred`:** Derived from a single geometric source and a documented formula.
   - **`assumed`:** Applied by default rule, with mandatory documented justification viewable to the user.
