"""Calibrate the cosine-similarity thresholds on labelled sample photos.

Usage:
  python scripts/calibrate.py --pos samples/kohli --neg samples/neg [--thumb 150] [--markdown]

Prints same-person cosines (full size and thumbnail-vs-full), impostor cosines, and the
recommended MATCH_THRESHOLD / REVIEW_THRESHOLD following the rule in the build plan:
  MATCH  = max(0.45, neg_max + 0.05) if >= 90 % of positive pairs pass, else lowered toward 0.40
  REVIEW = clip((neg_max + pos_min) / 2, 0.30, 0.42)
"""

from __future__ import annotations

import argparse
import io
import statistics
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

from facechain.face.engine import get_engine
from facechain.face.match import cosine

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def thumbnail_bytes(path: Path, width: int) -> bytes:
    img = Image.open(path).convert("RGB")
    h = max(1, round(img.height * width / img.width))
    buf = io.BytesIO()
    img.resize((width, h), Image.Resampling.LANCZOS).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def largest_embedding(data: bytes) -> np.ndarray | None:
    faces = get_engine().embed_bytes(data)
    return faces[0].embedding if faces else None


def images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def describe(name: str, sims: list[float]) -> str:
    if not sims:
        return f"{name:28s} n=0"
    return (
        f"{name:28s} n={len(sims):<3d} min={min(sims):.3f} "
        f"median={statistics.median(sims):.3f} max={max(sims):.3f}"
    )


def recommend(pos: list[float], neg: list[float]) -> tuple[float, float]:
    neg_max = max(neg) if neg else 0.0
    pos_min = min(pos) if pos else 1.0
    match = max(0.45, round(neg_max + 0.05, 2))
    while match > 0.40 and pos and sum(s >= match for s in pos) / len(pos) < 0.90:
        match = round(match - 0.01, 2)
    review = min(0.42, max(0.30, round((neg_max + pos_min) / 2, 2)))
    return match, review


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pos", type=Path, required=True, help="folder of photos of ONE person")
    ap.add_argument("--neg", type=Path, required=True, help="folder of photos of OTHER people")
    ap.add_argument(
        "--thumb", type=int, default=150, help="thumbnail width for cross-resolution pairs"
    )
    ap.add_argument("--markdown", action="store_true", help="also print a README-ready table")
    args = ap.parse_args()

    pos_paths, neg_paths = images(args.pos), images(args.neg)
    pos = [(p, largest_embedding(p.read_bytes())) for p in pos_paths]
    neg = [(p, largest_embedding(p.read_bytes())) for p in neg_paths]
    thumbs = [(p, largest_embedding(thumbnail_bytes(p, args.thumb))) for p in pos_paths]

    for label, items in (("pos", pos), ("neg", neg), ("thumb", thumbs)):
        for p, e in items:
            if e is None:
                print(f"!! no face in {label}: {p.name}", file=sys.stderr)

    pos_e = [(p, e) for p, e in pos if e is not None]
    neg_e = [(p, e) for p, e in neg if e is not None]
    thumb_e = {p: e for p, e in thumbs if e is not None}

    same_full = [cosine(a, b) for (_, a), (_, b) in combinations(pos_e, 2)]
    same_thumb = [
        cosine(thumb_e[p], e2) for p, _ in pos_e if p in thumb_e for q, e2 in pos_e if q != p
    ]
    impostor = [cosine(a, b) for _, a in pos_e for _, b in neg_e]
    impostor_thumb = [cosine(thumb_e[p], b) for p in thumb_e for _, b in neg_e]

    print(describe("same person (full)", same_full))
    print(describe(f"same person (thumb {args.thumb}px)", same_thumb))
    print(describe("impostor (full)", impostor))
    print(describe(f"impostor (thumb {args.thumb}px)", impostor_thumb))

    match, review = recommend(same_full + same_thumb, impostor + impostor_thumb)
    print(f"\nrecommended MATCH_THRESHOLD={match:.2f}  REVIEW_THRESHOLD={review:.2f}")

    if args.markdown:
        print("\n| pairs | n | min | median | max |\n|---|---|---|---|---|")
        for name, sims in (
            ("same person, full size", same_full),
            (f"same person, {args.thumb}px thumbnail vs full", same_thumb),
            ("impostor, full size", impostor),
            (f"impostor, {args.thumb}px thumbnail", impostor_thumb),
        ):
            if sims:
                print(
                    f"| {name} | {len(sims)} | {min(sims):.3f} | "
                    f"{statistics.median(sims):.3f} | {max(sims):.3f} |"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
