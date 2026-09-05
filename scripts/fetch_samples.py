"""Download CC-licensed sample photos from Wikimedia Commons and write samples/SOURCES.md.

Usage: python3 scripts/fetch_samples.py            (stdlib only; safe to run before the venv exists)

The manifest below is the single place that decides which public-figure photos are used for
development and calibration. Every file's licence, author and source URL are recorded in
samples/SOURCES.md so the repo stays attributable.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = "facechain-hackathon/0.1 (https://github.com/Vishal4742/facechain; contact via GitHub)"
API = "https://commons.wikimedia.org/w/api.php"
ROOT = Path(__file__).resolve().parents[1] / "samples"
MAX_WIDTH = 1280

# subject -> list of Commons file titles (without the "File:" prefix); first entry is subject.jpg
MANIFEST: dict[str, list[str]] = {
    "kohli": [
        "Virat Kohli portrait.jpg",
        "Virat Kohli in PMO New Delhi.jpg",
        "Virat Kohli during the India vs Aus 4th Test match at Narendra Modi Stadium on 09 March 2023.jpg",  # noqa: E501
        "Virat Kohli in New Delhi in December 2018.jpg",
        "VIRAT KOHLI JAN 2015 (cropped).jpg",
    ],
    "ronaldo": [
        "Cristiano Ronaldo Croatia v Portugal 2 July 2026-154(cropped).jpg",
        "Cristiano Ronaldo 2018 (cropped).jpg",
        "Cristiano Ronaldo - Croatia vs. Portugal, 10th June 2013 (cropped).jpg",
        "Cristiano Ronaldo, 2010.jpg",
    ],
    "hamilton": [
        "Lewis Hamilton, British GP 2022 (52382788875) (cropped).jpg",
        "Lewis Hamilton 2022 São Paulo Grand Prix (52498120773) (cropped).jpg",
        "Lewis Hamilton, 2019 Canadian Grand Prix (cropped).jpg",
        "Lewis Hamilton 2021.jpg",
    ],
}

# impostors for calibration: other public figures, resolved by search (first usable JPEG)
NEGATIVE_SEARCHES: list[str] = [
    "Rohit Sharma cricketer",
    "KL Rahul cricketer",
    "Hardik Pandya",
    "Lionel Messi 2022",
    "Neymar 2019",
    "George Russell racing driver",
    "Valtteri Bottas 2021",
    "Shikhar Dhawan",
]


def api(params: dict[str, str]) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def imageinfo(titles: list[str]) -> dict[str, dict]:
    data = api(
        {
            "action": "query",
            "titles": "|".join("File:" + t for t in titles),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": str(MAX_WIDTH),
        }
    )
    out: dict[str, dict] = {}
    for page in data.get("query", {}).get("pages", {}).values():
        infos = page.get("imageinfo") or []
        if infos:
            out[page["title"][5:]] = infos[0]
    return out


def search_first_jpeg(query: str) -> tuple[str, dict] | None:
    data = api(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": "15",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": str(MAX_WIDTH),
        }
    )
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") != "image/jpeg" or int(info.get("width", 0)) < 400:
            continue
        if int(info.get("height", 0)) < int(info.get("width", 0)) * 0.8:
            continue  # prefer portrait-ish framing (more likely a single face)
        return page["title"][5:], info
    return None


def clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def slug(title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", title.rsplit(".", 1)[0]).strip("-").lower()
    return base[:60] + ".jpg"


def main() -> int:
    rows: list[str] = []

    def record(subject: str, local: Path, title: str, info: dict) -> None:
        em = info.get("extmetadata", {})
        rows.append(
            "| {} | `{}` | {} | {} | {} | [{}]({}) |".format(
                subject,
                local.relative_to(ROOT.parent).as_posix(),
                clean(em.get("LicenseShortName", {}).get("value", "?")),
                clean(em.get("Artist", {}).get("value", "?"))[:60],
                clean(em.get("DateTimeOriginal", {}).get("value", "?"))[:10],
                title,
                info.get("descriptionurl", ""),
            )
        )

    for subject, titles in MANIFEST.items():
        infos = imageinfo(titles)
        for i, title in enumerate(titles):
            info = infos.get(title)
            if not info:
                print(f"!! not found on Commons: {title}", file=sys.stderr)
                continue
            url = info.get("thumburl") or info["url"]
            local = ROOT / subject / ("subject.jpg" if i == 0 else f"alt-{i}-{slug(title)}")
            n = download(url, local)
            print(f"{local.relative_to(ROOT.parent)}  {n // 1024} KB")
            record(subject, local, title, info)

    for q in NEGATIVE_SEARCHES:
        found = search_first_jpeg(q)
        if not found:
            print(f"!! no usable result for: {q}", file=sys.stderr)
            continue
        title, info = found
        url = info.get("thumburl") or info["url"]
        local = ROOT / "neg" / slug(title)
        n = download(url, local)
        print(f"{local.relative_to(ROOT.parent)}  {n // 1024} KB   <- {q}")
        record("neg", local, title, info)

    header = [
        "# Sample image sources",
        "",
        "All images come from Wikimedia Commons under the licence listed. They are used only to",
        "develop and demonstrate the pipeline. Regenerate this file with `python3 scripts/fetch_samples.py`.",  # noqa: E501
        "",
        "| subject | local file | licence | author | date | source |",
        "|---|---|---|---|---|---|",
    ]
    (ROOT / "SOURCES.md").write_text("\n".join(header + rows) + "\n", encoding="utf-8")
    print(f"wrote {ROOT / 'SOURCES.md'} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
