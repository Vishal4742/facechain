# Phase 5 — Identity hop, X path, IPFS

Date: 2026-09-05

## Built
- `search/identity.py` — Lens hint → Wikidata: Knowledge Graph id (from the `related_content` link) via P2671 first, then name search restricted to humans whose label matches the hint; verified handles P2002/P2003/P2013/P7085/P2397.
- `search/platforms/x.py` — syndication timeline (`__NEXT_DATA__` parse, posts with media), tweet-result hydration for x.com posts found by Lens, candidate conversion; timeline always served from cache (rate limit ≈ 30/15 min per IP).
- `pipeline` — engines `lens,identity`; names mined from candidate titles when Lens gives no hint; social posts first with engines interleaved; identity-authored candidates corroborated (`identity:@handle`).
- `chain/ipfs.py` — Pinata pin of post media (before hashing, `media_cid` in the bundle) and of `bundle.json` (CID in the memo); `verify --cid` materialises a run from IPFS. Unit-tested with a fake HTTP layer and exercised live on 2026-09-05: media and bundle pinned, CID in the memo, `verify --cid` VERIFIED from IPFS alone.

## Verified (real output)
- Wikidata: Ronaldo Q11571 → @Cristiano / @cristiano / @Cristiano / YouTube; Hamilton Q9673 → @LewisHamilton; Kohli Q213854 → Instagram/Facebook only; "cricketer" → no identity (label check).
- X: `@Cristiano` timeline → 30 posts with media; 20 verified in the sample run, best 0.707, all corroborated `identity:@Cristiano`.
- Ronaldo run: 90 unique candidates (60 Lens + 30 identity), ACCEPT 0.878 (Instagram post), 33 candidates ≥ 0.40.

## Decisions
- P2671 is absent for all three subjects on Wikidata, so the name route with a label-equality/containment check is the effective path; generic hints resolve to nothing.
- Path B is additive: it never blocks a run (timeline 429 → 0 posts, search continues).

## Open
- YouTube Data API path was cut (plan cut line).
