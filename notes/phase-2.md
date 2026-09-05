# Phase 2 — Lens search + face-verified ranking

Date: 2026-09-05

## Built
- `search/filters.py` — platform detection for 8 social platforms, post-vs-profile regexes, canonical URLs (twitter/mobile → x.com, youtu.be → watch?v=, tracking params stripped, content params kept), author handles.
- `search/base.py` — frozen `Candidate` (canonical url, platform, is_post, author, media urls, engine + rank, `similarity_bps` int, band, corroboration signals, media bytes/sha) and `Hint` (Lens identity hint with Knowledge Graph id).
- `search/lens.py` — SerpApi image upload (`POST /image`, ≤ 480 KB JPEG) + `google_lens` visual and exact matches; raw response cached by image sha256 before parsing; `search_metadata.id/created_at` recorded per call (live-proof); empty results never cached; recorded fixture replay only when a live call fails, with a red banner.
- `search/media.py` — cached, parallel media download with browser UA and referer; X media upgraded to `name=large`.
- `search/rank.py` — per-candidate face embedding, best-face cosine, quality gate (low-quality-only faces cap at "review"), `corroborate` (same URL/author from another engine), `accept` (winner = best social POST in the match band; accepted only with ≥ 2 candidates ≥ 0.40 or an explicit corroboration signal), rich table.
- `pipeline.run_search` shared by `facechain search` and `facechain run`.

## Verified (real output)
- Specs written first: `pytest tests/test_filters.py tests/test_lens_parse.py tests/test_accept.py` → 3 collection errors (RED); after implementation 82 passed, pyright clean.
- Live Lens call: **not yet run** — waiting for the SerpApi key in `.env`. First live run must record: search id, created_at, number of social candidates, winner similarity, searches left.

## Decisions
- Non-social candidates are still face-verified (they corroborate identity) but only social post URLs can win.
- Faces failing the quality gate can never produce a "match" band on their own.
- Reviewer fixes folded in: secrets redacted from HTTP errors, per-write temp files in the cache, mid-stream download failures return None, InsightFace chatter redirected to stderr, transient empty Lens results are not cached.

## Open
- Subject selection (Kohli first, Ronaldo, Hamilton) happens with the first live searches; record scores in `samples/SOURCES.md`.
- Instagram `image` URLs from Lens may 403 without cookies; the gstatic thumbnail fallback covers that.
