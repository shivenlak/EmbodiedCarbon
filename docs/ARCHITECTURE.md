# How ecarbon works

A plan set goes in; a traceable bill of quantities and an A1–A3 embodied-carbon figure come out. Every number says whether it was **measured** off the linework, **inferred** from something a sheet states, or **assumed** from a stated standard, and every number traces back to the sheet it came from.

## The flow

```mermaid
flowchart TD
    U["Upload: one PDF, or several files of one set<br/><small>api/main.py · POST /projects/upload</small>"]
    J["Join the files into one set<br/><small>config.folder_design</small>"]
    I["Inventory: classify every sheet, find its scale<br/><small>intake/inventory.py · intake/classify.py · geometry/scale.py</small>"]
    L["Locale: units and country<br/><small>intake/locale.py</small>"]
    R["Rules: read what the drawings state<br/><small>geometry/footprint.py · extract/levels.py<br/>extract/assemblies.py · extract/openings.py<br/>extract/specs.py · geometry/partitions.py</small>"]
    V["Vision fallback, only where the rules failed<br/><small>vision/ · quote-and-locate check · in progress</small>"]
    H["Help it read this, only where both failed<br/><small>HelpRead.jsx · POST /calibrate · takeoff/overrides.py</small>"]
    T["Takeoff: one line per element and material layer<br/><small>takeoff/builder.py</small>"]
    S["Standards for what the drawings defer<br/><small>takeoff/framing.py: joists, trusses, steel studs (ASSUMED)</small>"]
    G["Gaps: what it could not read, and why<br/><small>intake/gaps.py · builder</small>"]
    F["Factors by region<br/><small>carbon/store.py · carbon/region.py · seed_factors.json</small>"]
    C["Carbon: quantity × factor, with a range<br/><small>carbon/calculate.py</small>"]
    UI["The answer: 3D model, bill, trace to the sheet,<br/>metric or imperial, exports<br/><small>web/src: Showcase.jsx · App.jsx · scene.js · units.js</small>"]
    A["Accuracy: against the BIM model, the energy model<br/>and CMHC's own LCA<br/><small>scripts/accuracy.py → Accuracy tab</small>"]

    U --> J --> I --> L --> R
    R -- "a sheet, scale or schedule it can't read" --> V
    V -- "still missing" --> H
    R --> T
    V --> T
    H -- "you said" --> T
    T --> S --> C
    T --> G
    L --> F --> C
    C --> UI
    G --> UI
    UI -. "every line" .-> I
    C -.-> A
```

## The labels, and why they matter

| Label | Means | Example |
|---|---|---|
| measured | taken off the linework, corroborated by a second source | the footprint, agreeing with the dimension strings |
| inferred | computed from something a sheet states | slab volume = measured footprint × the stated thickness |
| assumed | a stated standard stood in, and the line says which | I-joists at 302 mm, 400 mm centres, where the structure is deferred |
| "you said" | the user supplied it in *Help it read this* | a scale from two clicks and "23'-6\"" |
| "read by AI" | a vision model read it, and the quote was found on the sheet | a schedule on a scanned page |

What the tool cannot read, it says so on the bill rather than guessing. It also never sums across life-cycle modules: the figure is A1–A3 only.

## Where the code lives

| Area | Module |
|---|---|
| Sheet inventory and classification | `ecarbon/intake/` |
| Geometry: scale, footprint, partitions | `ecarbon/geometry/` |
| Text: levels, assemblies, openings, specs | `ecarbon/extract/` |
| Vision fallback | `ecarbon/vision/` |
| The bill | `ecarbon/takeoff/builder.py`, `framing.py`, `overrides.py` |
| Carbon and factors | `ecarbon/carbon/` |
| API | `ecarbon/api/main.py` |
| Interface | `web/src/` |
| Benchmarks | `ecarbon/bench/`, `scripts/accuracy.py`, `scripts/score_blind.py` |
