#!/usr/bin/env python3
"""IFC concrete by element type, with each layer's modelled thickness.

    python scripts/ifc_concrete.py out/ifc_concrete.json

Why: 15 of the CMHC IFC models tag the whole 454 mm slab build-up as concrete
(the drawings state 100-130 mm), which made our slab look 3.5x under-counted.
scripts/accuracy.py reads this file to compare concrete only where the
model's slab is a plausible slab. Output stays in out/ (ignored): it quotes
per-design figures from licensed models.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecarbon.bench.ifc_quantities import model_quantities  # noqa: E402
from ecarbon.config import discover  # noqa: E402
from ecarbon.extract.specs import foundation_spec_for  # noqa: E402


def survey(design) -> dict:
    mq = model_quantities(design.ifc)
    by: dict[str, list] = defaultdict(lambda: [0.0, set()])
    for element in mq.elements:
        for layer in element.layers:
            if "Concrete" in layer.material:
                by[element.ifc_type][0] += layer.volume_m3
                by[element.ifc_type][1].add(round(layer.thickness_mm))
    row: dict = {k: [round(v[0], 1), sorted(v[1])] for k, v in by.items()}
    row["IfcFooting_solid"] = round(
        sum(e.net_volume_m3 for e in mq.elements if e.ifc_type == "IfcFooting"), 1
    )
    try:
        row["drawings_slab_mm"] = foundation_spec_for(design).slab_thickness_mm
    except Exception:
        row["drawings_slab_mm"] = None
    return row


def main(argv: list[str]) -> int:
    out_path = Path(argv[0]) if argv else Path("out/ifc_concrete.json")
    out: dict[str, dict] = {}
    for design in discover():
        if not design.ifc:
            continue
        try:
            out[design.key] = survey(design)
        except Exception as exc:  # one unreadable model must not stop the rest
            print(f"{design.key[:34]:34} IFC unreadable: {exc}")
            continue
        r = out[design.key]
        print(f"{design.key[:34]:34} slab {r.get('IfcSlab')}  walls {r.get('IfcWall')}  "
              f"footings {r['IfcFooting_solid']}  drawn slab {r['drawings_slab_mm']}")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
