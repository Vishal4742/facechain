# Phase 1 — Face engine + calibration

Date: 2026-09-05

## Built
- `facechain/face/types.py` — frozen `Face` (bbox, 5 kps, det_score, 512-d normed embedding, ipd_px, blur_var, area).
- `facechain/face/match.py` — `cosine`, `band` (inclusive thresholds), `best_similarity`, `quality_ok` (det ≥ 0.60, ipd ≥ 25 px, Laplacian var ≥ 60), `pick_query_face` (largest or explicit index).
- `facechain/face/engine.py` — InsightFace `buffalo_l` with only detection + recognition modules loaded; EXIF-aware decode; 2× Lanczos upscale retry at det_thresh 0.3 for small images; coordinates always in source pixels; process-wide singleton behind a lock.
- `facechain scan --image F [--face-index N] [--json]`.
- `scripts/calibrate.py --pos DIR --neg DIR [--thumb 150] [--markdown]`.

## Verified (real output)
- `facechain scan --image samples/kohli/subject.jpg` → `1 face(s) in 2.2s`, bbox 326 338 987 1134, det 0.88, ipd 295 px, blur 134, quality ok.
- Calibration (6 impostors: Rohit Sharma, Hardik Pandya, Messi, Neymar, George Russell, Shikhar Dhawan):

| subject | same-person full (min / median / max) | same-person 150 px thumb vs full (min / median) | impostor max (full / thumb) | recommended |
|---|---|---|---|---|
| kohli | 0.530 / 0.712 / 0.836 | 0.498 / 0.684 | 0.155 / 0.152 | match 0.45, review 0.33 |
| ronaldo | 0.467 / 0.569 / 0.626 | 0.415 / 0.537 | 0.191 / 0.167 | match 0.42, review 0.30 |
| hamilton | 0.439 / 0.563 / 0.701 | 0.264 / 0.533 | 0.138 / 0.136 | match 0.40, review 0.30 |

## Decisions
- Keep defaults `MATCH_THRESHOLD=0.45`, `REVIEW_THRESHOLD=0.35`: impostors never exceed 0.19, so the margin below 0.45 is wide; the review band catches low-resolution true matches (Hamilton thumbnails dip to 0.26, so his photos are the weakest candidate set). Kohli has the cleanest separation and stays first choice.
- Candidates ≥ 0.40 count toward corroboration (acceptance rule in the plan).
- `tests/` is a package so `tests.conftest.requires_model` imports; Pillow resampling via `Image.Resampling.LANCZOS` (pyright).

## Open
- Blur gate (Laplacian var ≥ 60) is untested on real Lens thumbnails; revisit in Phase 2 if good faces get rejected.

## Next phase needs
- SerpApi key in `.env` for live Lens calls; `search` command; candidate filters and ranking.
