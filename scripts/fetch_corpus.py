#!/usr/bin/env python3
"""Download the global corpus listed in corpus/sources.yaml.

    python scripts/fetch_corpus.py --split dev        # Stream A: dev sets only
    python scripts/fetch_corpus.py --split holdout    # Stream B only
    python scripts/fetch_corpus.py --list             # what is listed, and what is on disk

Files land in ~/ec-data/global/<id>/planset.pdf (override with $EC_GLOBAL),
outside the repository. Plan sets never enter git.

Some sites refuse scripted downloads. Those are marked `fetch: browser`: this
script prints the URL, and you save the file by hand to the path it names. A
file that is already present is checked against its recorded sha256 prefix and
left alone.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "corpus" / "sources.yaml"
UA = "ecarbon-corpus-fetch/1.0"


def corpus_root() -> Path:
    return Path(os.environ.get("EC_GLOBAL", Path.home() / "ec-data" / "global"))


def load_sets() -> list[dict]:
    return yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sets"]


def sha_prefix(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def fetch(entry: dict, dest: Path) -> str:
    want = entry.get("sha256")
    if dest.is_file():
        if want and sha_prefix(dest, len(want)) != want:
            return f"present but sha256 differs from {want}: check the file"
        return "present"
    if not entry.get("url"):
        return f"no file URL yet; find it on {entry.get('page')}"
    if entry.get("fetch") == "browser":
        return f"open {entry['url']} in a browser and save it as {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(entry["url"], headers={"User-Agent": UA})
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=180) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if tmp.read_bytes()[:5] != b"%PDF-":
        tmp.unlink()
        return "download was not a PDF (blocked?); fetch it in a browser"
    tmp.rename(dest)
    if want and sha_prefix(dest, len(want)) != want:
        return f"downloaded, but sha256 differs from {want}: the source changed"
    return "downloaded"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--split", choices=["dev", "holdout"])
    g.add_argument("--list", action="store_true")
    args = ap.parse_args()

    root = corpus_root()
    sets = load_sets()
    if args.list:
        for e in sets:
            on_disk = (root / e["id"] / "planset.pdf").is_file()
            print(f"{e['split']:8} {e['id']:28} {e.get('country', '?'):3} "
                  f"{e.get('units', '?'):9} {'on disk' if on_disk else '-'}")
        return 0

    failures = 0
    for e in (x for x in sets if x["split"] == args.split):
        dest = root / e["id"] / "planset.pdf"
        try:
            status = fetch(e, dest)
        except Exception as exc:  # network errors are reported, not fatal
            status = f"failed: {exc}"
        if status not in ("present", "downloaded"):
            failures += 1
        print(f"{e['id']:28} {status}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
