#!/usr/bin/env python
"""Download the third-party methodology references into reference/ (gitignored).

These are other people's publications. We do not redistribute them -- the repo
stores the download recipe, not the files.

Two of these are not optional reading:
  * Kootenay Material Impact Guide -- the challenge scope's Stage 2 says to
    prioritise elements "using this guide". It sets our build order.
  * NRC National Guidelines for wbLCA -- the Canadian methodology the judges'
    "defensible" standard points at.

Anything that needs a browser (an account, JS rendering, or a click-through) is
listed by MANUAL[] and printed as a to-do rather than silently skipped.
"""

from __future__ import annotations

import http.cookiejar
import urllib.error
import urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "reference"

# nrc-publications.canada.ca serves HTTP 410 to the full Chrome UA string but 200
# to a short one. Others are happy with either, so we try the short one first.
USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
UA = USER_AGENTS[0]

NRC_LANDING = "https://nrc-publications.canada.ca/eng/view/object/?id=f7bd265d-cc3d-4848-a666-8eeb1fbde910"

DOWNLOADS: list[tuple[str, str, str]] = [
    (
        "kootenay_material_impact_guide.pdf",
        "https://www.buildersforclimateaction.org/uploads/1/5/9/3/15931000/kootenay_construction_-_material_impact_guide.pdf",
        "Builders for Climate Action -- Material Impact Guide. PRESCRIBED by the "
        "challenge scope Stage 2; sets our element build order -> docs/element_priority.md.",
    ),
    (
        "nrc_national_guidelines_wblca.pdf",
        "https://nrc-publications.canada.ca/eng/view/ft/?id=f7bd265d-cc3d-4848-a666-8eeb1fbde910",
        "NRC National Guidelines for Whole-Building LCA (2022, 136 pp). "
        "Canadian wbLCA methodology; DOI 10.4224/40002740. Needs a session cookie "
        "from the landing page first, else returns HTTP 410.",
    ),
    (
        "ec3_primer_for_aec_professionals.pdf",
        "https://www.buildingtransparency.org/wp-content/uploads/2024/08/ec3-primer_for_aec_professionals.pdf",
        "EC3 primer -- EPD selection and uncertainty framing.",
    ),
    (
        "istructe_brief_guide_embodied_carbon.pdf",
        "https://www.istructe.org/IStructE/media/Public/TSE-Archive/2020/A-brief-guide-to-calculating-embodied-carbon.pdf",
        "IStructE -- the canonical formulae: EC = sum(qty x ECF), "
        "A5w = WF x (A1-A3 + A4 + C2 + C3-C4).",
    ),
]

MANUAL: list[tuple[str, str]] = [
    (
        "CMHC Construction Cost Estimates (+ sample LCAs, Materials Guide, Climate Resilience Guide)",
        "https://www.housingcatalogue.cmhc-schl.gc.ca/ -- per design. The cost estimates "
        "contain published QUANTITY TAKE-OFFS (CIQS Class B, +/-15%), which is the closest "
        "thing to a reference takeoff we can get. Site is JS-rendered; needs a browser. "
        "HIGHEST-VALUE outstanding item -- see RESEARCH.md §6.",
    ),
    (
        "BEAM estimator",
        "https://www.buildersforclimateaction.org/beam-estimator.html -- Google Sheet, "
        "pay-what-you-can. A1-A3, Canadian, low-rise residential: the best methodology fit. "
        "READ THE EULA before copying factors into our store.",
    ),
    (
        "EC3 EPD snapshot",
        "https://buildingtransparency.org/ec3/manage-apps -- needs a Professional account "
        "with a business email. Free tier: 10,000 tokens/month. Attribution to Building "
        "Transparency is required wherever its data is displayed.",
    ),
    (
        "Autodesk sustainability API data providers",
        "https://aps.autodesk.com/en/docs/sustainability/v3/developers_guide/data_providers/"
        "available-data-providers-and-datasets -- JS-rendered docs; needs a browser.",
    ),
    (
        "Sponsor element/material list + wbLCA template",
        "NOT PUBLISHED. The scope references both as 'attached in the data package' but "
        "the data package is 2 pages of links. Email the organisers -- RESEARCH.md §1.",
    ),
]

DO_NOT_USE = [
    (
        "ICE Database (University of Bath)",
        "Educational edition forbids commercial use, including 'tools, software, reporting, "
        "or any internal business activity'. Commercial use needs the paid IC+ licence. "
        "The challenge data package lists it as free/open -- misleading for our purpose.",
    ),
]


def _curl(url: str, referer: str | None = None, ua: str = UA) -> bytes:
    """Fall back to curl, which handles cookies/redirects more forgivingly."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("curl"):
        return b""
    with tempfile.TemporaryDirectory() as tmp:
        jar = Path(tmp) / "cookies"
        out = Path(tmp) / "dl"
        if referer:
            subprocess.run(
                ["curl", "-sL", "-c", str(jar), "-A", ua, "-o", "/dev/null",
                 "--max-time", "60", referer],
                check=False, capture_output=True,
            )
        cmd = ["curl", "-sL", "-A", ua, "--max-time", "180", "-o", str(out)]
        if referer:
            cmd += ["-b", str(jar), "-e", referer]
        cmd.append(url)
        subprocess.run(cmd, check=False, capture_output=True)
        return out.read_bytes() if out.exists() else b""


def fetch(name: str, url: str, note: str) -> bool:
    REF.mkdir(parents=True, exist_ok=True)
    dest = REF / name
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"  [have] {name}  ({dest.stat().st_size/1e6:.1f} MB)")
        return True

    # The NRC full-text endpoint also needs a session cookie from the record's
    # landing page, presented with that page as referer.
    referer = NRC_LANDING if "nrc-publications" in url else None

    data = b""
    err: str | None = None
    for ua in USER_AGENTS:
        headers = {"User-Agent": ua, "Accept": "application/pdf,*/*"}
        opener = urllib.request.build_opener()
        if referer:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            try:
                opener.open(urllib.request.Request(referer, headers=headers), timeout=60).read()
            except Exception:
                pass
            headers["Referer"] = referer
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=180) as resp:
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            err = err or str(exc)
        if data.startswith(b"%PDF"):
            break
        # curl negotiates redirects, cookies and TLS quirks that urllib trips on.
        got = _curl(url, referer=referer, ua=ua)
        if got.startswith(b"%PDF"):
            data = got
            break

    if not data.startswith(b"%PDF"):
        detail = err or f"not a PDF ({len(data)} bytes, starts {data[:16]!r})"
        print(f"  [FAIL] {name}: {detail}")
        print(f"         download by hand -> {url}")
        return False
    dest.write_bytes(data)
    print(f"  [get ] {name}  ({len(data)/1e6:.1f} MB)")
    print(f"         {note}")
    return True


def main() -> int:
    print(f"reference/ -> {REF}\n")
    print("Downloading:")
    ok = sum(fetch(*row) for row in DOWNLOADS)
    print(f"\n{ok}/{len(DOWNLOADS)} downloaded.\n")

    print("MANUAL -- needs a browser, an account, or an email:")
    for title, note in MANUAL:
        print(f"  * {title}\n      {note}")

    print("\nDO NOT USE:")
    for title, why in DO_NOT_USE:
        print(f"  * {title}\n      {why}")

    return 0 if ok == len(DOWNLOADS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
