"""Copy the cache entries a run touched into tests/fixtures/cache so tests and the labelled
replay path can work offline.

Usage: python scripts/export_fixtures.py --run evidence/<run_id> [--max-kb 100]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from facechain.config import load

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cache"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--max-kb", type=int, default=100, help="skip binary entries larger than this")
    args = ap.parse_args()

    keys_file = args.run / "cache_keys.txt"
    if not keys_file.exists():
        print(f"no cache_keys.txt in {args.run}", file=sys.stderr)
        return 1
    cache_root = load().cache_dir
    copied = skipped = 0
    for line in keys_file.read_text().splitlines():
        if "/" not in line:
            continue
        namespace, key = line.strip().split("/", 1)
        src_dir = cache_root / namespace / key[:2]
        for src in src_dir.glob(f"{key}*"):
            if src.suffix == ".bin" and src.stat().st_size > args.max_kb * 1024:
                skipped += 1
                continue
            dst = FIXTURES / namespace / key[:2] / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    print(f"copied {copied} files into {FIXTURES} (skipped {skipped} large binaries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
