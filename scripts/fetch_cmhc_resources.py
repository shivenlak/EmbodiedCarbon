#!/usr/bin/env python
"""Download the CMHC Housing Design Catalogue resource documents.

These are NOT part of the per-design Technical Design Packages and are easy to
miss: the catalogue's design listing is an Angular app, but
/how-it-works/resources is server-rendered and links every file directly on
assets.cmhc-schl.gc.ca. No browser is needed.

The two that matter:

  * Materials Guide -- a published Canadian carbon factor table, per m2 at a
    stated thickness, covering every Stage 4 substitution the scope names.
    WARNING: its embodied carbon column is A-C whole-life, NOT A1-A3. Only the
    biogenic column is A1-A3. See RESEARCH.md S16.
  * Construction Cost Estimate summaries -- Class B cost RANGES by Vermeulens.
    They contain no quantities; the detailed takeoff was not published. They do
    give gross building area and leasable area per unit, which corroborate the
    Building Performance Reports' floor areas.

Files land in reference/cmhc/, which is gitignored: these are CMHC's documents
and we store the download recipe, not the files.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "reference" / "cmhc"
BASE = "https://assets.cmhc-schl.gc.ca/sites/housing%20catalog/resources"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# (local name, path under BASE, note)
DOCS: list[tuple[str, str, str]] = [
    (
        "materials-guide.pdf",
        "housing-hesign-catalogue-materials-guide-en.pdf?rev=aafca114-08f0-4e87-af22-d8bfc18932c4",
        "Carbon factor table, kgCO2e/m2. A-C scope, NOT A1-A3 -- see RESEARCH S16.",
    ),
    (
        "climate-resilience-guide.pdf",
        "climate-resilience-guide-housing-design-catalogue-en.pdf?rev=bd94bcee-2f5d-4d74-bf78-af34d41ad3c3",
        "Context for the implementation plan.",
    ),
    (
        "cost-alberta.pdf",
        "hdc-construction-cost-estimate-summary-alberta-en.pdf?rev=fdf9b220-e965-4095-b3f2-71d9e3ad422b",
        "Class B cost ranges + gross/leasable floor areas. No quantities.",
    ),
    (
        "cost-atlantic.pdf",
        "hdc-construction-cost-estimate-summary-atlantic-en.pdf?rev=24c4125d-cced-41fc-8e27-6d842cc4ca39",
        "",
    ),
    (
        "cost-bc.pdf",
        "hdc-construction-cost-estimate--summary-british-columbia-en.pdf?rev=423e6d94-fb9f-4196-91fe-731433020e6a",
        "",
    ),
    (
        "cost-north.pdf",
        "hdc-construction-cost-estimate--summary-yk-nwt-nu-en.pdf?rev=61dd1bdc-183e-49fa-bc6b-e2f54eb8a017",
        "",
    ),
    (
        "cost-ontario.pdf",
        "hdc-construction-cost-estimate--summary-ontario-en.pdf?rev=0385f85c-c8cf-4e94-9588-982b15a6c1d4",
        "",
    ),
    (
        "cost-quebec.pdf",
        "hdc-construction-cost-estimate--summary-quebec-en.pdf?rev=1d2335bc-92c6-4033-a4e5-bcf176ad7a82",
        "",
    ),
    (
        "cost-skmb.pdf",
        "hdc-construction-cost-estimate--summary-saskatchewan-and-manitoba-en.pdf?rev=e73b3681-38a5-4187-a384-0f0ece86e498",
        "",
    ),
]

SITE_DESIGN = {
    "site-design-atlantic.pdf": "site-design-examples/atlantic-site-design-examples-guide-en.pdf?rev=3927895f-a3ce-44a4-aacd-9f27c6ae978d",
    "site-design-bc.pdf": "site-design-examples/bc-site-design-examples-guide-en.pdf?rev=5453c8e9-0c36-46ed-bdfb-3a2ef16dd578",
    "site-design-north.pdf": "site-design-examples/north-site-design-examples-guide-en.pdf?rev=84a84040-d446-42bc-a11d-724eb481ae8c",
    "site-design-ontario.pdf": "site-design-examples/ontario-site-design-examples-guide-en.pdf?rev=bf73ff28-cf84-48ca-aae5-054bd82ea11b",
    "site-design-quebec.pdf": "site-design-examples/quebec-site-design-examples-guide-en.pdf?rev=dc471e41-21ca-44c0-af47-df89e56e1845",
}

RESOURCES_PAGE = "https://www.housingcatalogue.cmhc-schl.gc.ca/how-it-works/resources"


def fetch(name: str, path: str, note: str) -> bool:
    REF.mkdir(parents=True, exist_ok=True)
    dest = REF / name
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"  [have] {name}  ({dest.stat().st_size/1e6:.1f} MB)")
        return True
    url = f"{BASE}/{path}"
    data = b""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass
    if not data.startswith(b"%PDF"):
        try:
            data = subprocess.run(
                ["curl", "-sL", "-A", UA, "--max-time", "180", url],
                check=False, capture_output=True,
            ).stdout
        except FileNotFoundError:
            data = b""
    if not data.startswith(b"%PDF"):
        print(f"  [FAIL] {name}  -- the ?rev= token changes when CMHC republishes;")
        print(f"         re-read {RESOURCES_PAGE} for current links")
        return False
    dest.write_bytes(data)
    print(f"  [get ] {name}  ({len(data)/1e6:.1f} MB)" + (f"  {note}" if note else ""))
    return True


def main() -> int:
    include_site = "--all" in sys.argv
    print(f"reference/cmhc -> {REF}\n")
    rows = list(DOCS) + ([(k, v, "") for k, v in SITE_DESIGN.items()] if include_site else [])
    ok = sum(fetch(*r) for r in rows)
    print(f"\n{ok}/{len(rows)} downloaded." + ("" if include_site else "  (--all adds site design examples)"))
    print(
        "\nReminder: the Materials Guide's embodied carbon column is A-C whole life,\n"
        "not A1-A3. Storing it as an A1-A3 factor would produce a confidently wrong\n"
        "total that looks well sourced. See RESEARCH.md S16."
    )
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
