# FaceChain — Architecture (HH Goa 2026, Task 3)

Working name: **facechain** (rename freely). Pipeline: **face scan → genuine multi-engine social search with face verification → IPFS evidence → Solana devnet attestation → independent re-verification + tamper test.**

Research basis: state of tools verified on 2026-09-04 (see §10).

---

## 1. Design principles

1. **Genuine search, provably.** Candidates come from live engines (Google Lens, identity hop via Wikidata + platform endpoints, optional face-native engines). Nothing is pre-picked. Every candidate and its score is printed.
2. **Face-verified, not image-verified.** Reverse image search only proposes candidates. Acceptance is decided by ArcFace embedding similarity between the query face and the face inside each candidate's media. This is what makes it *face identification* rather than duplicate-image lookup.
3. **Two independent discovery paths converge.** Path A is image-native (visual matches). Path B is identity-native (who is this → verified handles → real posts). Either alone satisfies the task; together they are robust.
4. **Evidence first.** Everything discovered is written into a per-run evidence directory. A canonical `bundle.json` is the single object that gets hashed, pinned and attested.
5. **Verification derivable from content alone.** The on-chain record address is derived from the bundle hash, so a third party with only the bundle (or only the IPFS CID) can find and check the record without any receipt from us.
6. **Privacy by construction.** Only hashes, a similarity score, a post URL and an IPFS CID go on-chain. The face embedding never leaves the machine. The query image is sent only to the search engine (SerpApi's upload expires in 10 minutes).

---

## 2. Component diagram

```mermaid
flowchart LR
    A[Input image] --> F[Face engine\nInsightFace buffalo_l\nSCRFD det + ArcFace 512-d]
    F -->|query embedding + face_id| S

    subgraph S[Search orchestrator]
        direction TB
        PA[Path A: visual\nSerpApi Google Lens\nvisual_matches + exact_matches\n(+ optional Vision WEB_DETECTION, Yandex)]
        PB[Path B: identity hop\nLens related_content → name\n→ Wikidata handles (X, IG, FB, TikTok, YT)\n→ X syndication / YouTube Data API → posts]
        PC[Path C: face-native (optional)\nFaceCheck.ID demo/paid, Search4Faces]
        PA --> POOL[Candidate pool\nurl, platform, media, title, engine]
        PB --> POOL
        PC --> POOL
        POOL --> FLT[Social-domain filter\npost-URL preference, dedupe]
        FLT --> RANK[Download media → detect faces\n→ embed → cosine vs query\n→ quality gates → rank]
    end

    RANK -->|top match ≥ threshold| E[Evidence bundle\nbundle.json (canonical) + media bytes\nH = sha256(bundle)]
    E --> I[IPFS pin (Pinata)\nCID]
    E --> C[Solana devnet tx\nSAS attestation (nonce = H)\n+ SPL Memo summary]
    I --> C
    C --> V[Verify\nrecompute H → derive PDA → fetch → compare\nmemo scan by registry wallet\n--tamper flips a byte → FAIL]
```

---

## 3. Stage 1 — Face engine

- **Library:** InsightFace 1.0.1 (pure-Python wheel, no Cython build) + onnxruntime CPU. Model pack `buffalo_l` (SCRFD-10GF detector + ArcFace ResNet50@WebFace600K, 512-d L2-normalised embeddings; auto-downloads ~326 MB to `~/.insightface/models/`).
- **Detection settings:** `det_size` Auto (dual-scale 128/640, good for thumbnails). For thumbnails that yield no face: lower `det_thresh` to 0.3–0.4 and retry after 2× Lanczos upscale.
- **Quality gates before scoring:** `det_score ≥ 0.6`, inter-pupil distance ≥ ~25 px, Laplacian-variance blur check on the crop. Optional stretch: eDifFIQA quality score via `uniface`.
- **Multiple faces:** query image → embed all faces, default to the largest (CLI flag to pick index). Candidate media → embed all faces, score = max cosine.
- **Decision bands (cosine on normed embeddings, calibrate on a few known pairs):** ≥ 0.45 match · 0.35–0.45 review (shown, not accepted) · < 0.35 reject.
- **face_id** recorded in evidence = `sha256(query image bytes)`. The embedding itself is never persisted outside the run directory.
- Fallback stack if ever needed: OpenCV YuNet + SFace (bundled with opencv-python, threshold 0.363).

---

## 4. Stage 2 — Search orchestrator

### Candidate model
```
Candidate { url, platform, post_id?, author?, title?, text?, media_url, media_bytes?, engine, engine_rank, similarity?, faces_found, decision }
```

### Path A — visual (primary, image-native)
- **SerpApi Google Lens** with the SerpApi Image API upload (`POST https://serpapi.com/image`, multipart, ≤ 500 KB, id valid 10 min) → `engine=google_lens&image_id=…`. No public image hosting needed.
- Two calls per query: `type=visual_matches` and `type=exact_matches`. Extract `visual_matches[]` / `exact_matches[]` (title, link, source, thumbnail, image) and `related_content[].query` (identity hint with `kgmid`).
- Free plan: 250 searches/month, 50/hour. **All responses are cached on disk keyed by image hash + params** so re-runs cost nothing.
- Optional second opinions (same interface): Google Cloud Vision `WEB_DETECTION` (accepts bytes; 1,000 free units/month; `webEntities` = identity hint, `pagesWithMatchingImages`), SerpApi Yandex reverse image (needs a public URL → imgbb with `expiration`).

### Path B — identity hop (secondary, identity-native)
1. Identity hint: Lens `related_content[].query` (or Vision `webEntities`, or Rekognition `RecognizeCelebrities`).
2. Wikidata: `wbsearchentities` name → QID; SPARQL for verified handles: P2002 (X), P2003 (Instagram), P2013 (Facebook), P7085 (TikTok), P2397 (YouTube channel).
3. Enumerate real posts for those handles:
   - **X:** find recent `x.com/<handle>/status/<id>` URLs (SerpApi web search `site:x.com/<handle>/status`, or the syndication timeline if it responds), then fetch each post's full JSON incl. media from `https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=1` (no auth, verified working) and/or `https://publish.x.com/oembed?url=…`.
   - **YouTube:** channel → uploads playlist → `playlistItems.list` (1 unit each; free 10k/day) → maxres thumbnails.
   - Instagram/Facebook/TikTok: anonymous content fetch is dead in 2026; these platforms only enter via Path A links + Lens thumbnails.
4. Every post's media goes through the same face verification.

### Path C — face-native engines (optional add-ons)
- **FaceCheck.ID API** (`/api/upload_pic` → `/api/search`; returns profile/post URLs + score). $0.30/search, crypto-only payment; `demo=true` is free for integration tests (small index, results not meaningful). Alternative: Apify "Face Search AI" actor (card, $10/1k results).
- **Search4Faces** (VK/OK/TikTok avatars, free test key by email) — low value for an Indian/global demo.

### Filter → rank → decide
- Keep links matching `instagram.com|x.com|twitter.com|facebook.com|tiktok.com|threads.net|youtube.com|linkedin.com|pinterest.com`. Prefer post URLs (`/p/`, `/reel/`, `/status/`, `/video/`, `watch?v=`) over profile URLs. Dedupe by canonical URL.
- Download media (Lens thumbnail/image or post media), run face verification, sort by similarity, apply bands.
- Output a **ranked table** (engine, platform, URL, faces, similarity, decision) — this table is the on-screen proof that the search is real.
- Winner = highest similarity ≥ match threshold. If both paths agree on the same person/URL, note it as corroborated.

---

## 5. Stage 3 — Evidence bundle

Per run: `evidence/<run_id>/` containing `query.jpg`, `candidates.json` (full ranked table), `post_media.<ext>`, `post.json` (raw platform payload when available), `bundle.json`, later `receipt.json`.

```json
{
  "version": 1,
  "query":   { "face_id": "<sha256 query image>", "detector": "scrfd_10g", "embedder": "arcface_r50_buffalo_l" },
  "post":    { "url": "...", "platform": "x", "post_id": "...", "author": "...", "text": "... or null",
               "media_url": "...", "media_sha256": "...", "text_sha256": "... or null", "fetched_at": 1725400000 },
  "match":   { "engine": "google_lens", "similarity": 0.71, "threshold": 0.45, "candidates_considered": 37, "corroborated_by": ["identity_hop"] },
  "pipeline":{ "git_commit": "...", "run_id": "..." }
}
```
- Canonical JSON: sorted keys, no whitespace, UTF-8. `H = sha256(canonical bundle)`. Media bytes are hashed exactly as downloaded.

---

## 6. Stage 4 — Storage and on-chain anchoring (Solana devnet)

### Off-chain evidence: IPFS via Pinata
- Free tier (1 GB / 500 files). `POST https://uploads.pinata.cloud/v3/files` (multipart `file`, `network=public`, `Authorization: Bearer <JWT>`) → CID for `bundle.json` and the media file (or a single CAR/tar). Fetch via `https://<gateway>.mypinata.cloud/ipfs/<cid>`.

### On-chain record: two transactions (memo from Python, attestation from the sidecar)
1. **Solana Attestation Service (SAS) attestation** — Solana Foundation's attestation standard, program `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG` (same id on devnet and mainnet).
   - One-time setup (`facechain setup-sas`): Credential `FACECHAIN` (authority = registry wallet) and Schema `FaceMatchV1` v1 `{ bundle_hash: String, cid: String, post_url: String, similarity_bps: u64 }` (layout `[12,12,12,3]`). Everything else lives in the bundle the hash commits to. Devnet: credential `Awhv5DjjmeeGZPxeMim1hW8yWKgMJtUFD2dX7BrArpzh`, schema `DNnsTXgmuPDsb3gKF8rgYsnRYP7h6qLEMC9udtxofpDD` (Phase 6).
   - Per record: `create_attestation` with **`nonce = Pubkey(H)`** so the attestation PDA `["attestation", credential, schema, nonce]` is derivable from the bundle alone. `expiry = 0`.
   - Implementation: TypeScript sidecar (`chain-ts/sas.ts`, `sas-lib@1.0.10` + `@solana/kit@5.5.1`, run by Node ≥ 22.6 type stripping) called from Python (`chain/sas.py`) with JSON in/out. (Python `saslibpy` requires solana<0.40; `anchorpy` is unmaintained — do not use either.)
2. **SPL Memo** (`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`) in its own transaction, sent first, with a ≤ 500-byte summary: `FACECHAIN/1 h=<H> media=<media_sha256> cid=<CID> sim=<bps> url=<post_url>`. Makes the record human-readable in explorers and gives a second, program-free lookup path.

Signed by the **registry wallet** (`~/.config/solana/id.json`, 8.86 SOL on devnet — enough; keep the pubkey in the README). Print signature + `https://explorer.solana.com/tx/<sig>?cluster=devnet`.

### Fallback / alternative
- **Memo-only** (pure Python, solana-py 0.40.3 `AsyncClient` + `spl.memo`): ships in ~2 h and already satisfies the task. Build this first; add SAS on top.
- **Custom Anchor 0.32.1 registry** (PDA `["record", H]`, ~1 day, ~1 SOL rent, manual instruction encoding from Python) — only if we want to show Anchor code instead of SAS. Stay on Anchor 0.32.1 (1.0.0 is breaking); deploy with `--no-idl`.

---

## 7. Stage 5 — Verification

`facechain verify --bundle evidence/<run>/bundle.json` (or `--cid <CID>`, which fetches the bundle + media from IPFS first):
1. Recompute `media_sha256` from the local/IPFS media and check it equals the bundle field (local integrity).
2. Recompute `H` from the canonical bundle.
3. **SAS path** (when `SAS_CREDENTIAL` / `SAS_SCHEMA` are set): derive the attestation PDA from `nonce = Pubkey(H)` → fetch → deserialize → compare `bundle_hash`, `cid`, `post_url`, `similarity_bps` with the bundle; check the attestation signer is the registry wallet. H is taken from the evidence as it is on disk: if the media no longer matches the bundle, the bundle is re-hashed with the actual media digest, so a tampered run derives a PDA nobody attested (`attestation ABSENT`). An attestation that exists but disagrees with the bundle or the registry → TAMPERED.
4. **Memo path:** `getSignaturesForAddress(registry)` → find the signature whose `memo` contains `h=<H>` → `getTransaction(jsonParsed)` → confirm signer, slot, block time.
5. Print **VERIFIED** with signature, slot, block time, explorer link.

`--tamper` copies the evidence, flips one byte of the media (or edits the caption), reruns steps 1–4 → media hash mismatch, `H'` ≠ `H`, PDA absent, no memo → **TAMPERED**. This contrast is the centrepiece of the screen recording.

---

## 8. CLI surface and demo script

```
facechain run    --image samples/subject.jpg            # end to end, pretty output
facechain scan   --image ... [--face-index N]           # stage 1 only
facechain search --image ... [--engines lens,identity]  # stage 2, prints ranked table
facechain anchor --run evidence/<run_id>                # pin + attest + memo
facechain verify --bundle ... | --cid ... [--tamper]
facechain setup-sas                                     # one-time credential + schema
```
Recording order: `run` (face → ranked candidates → winner → tx link) → open explorer → `verify` → `verify --tamper`.

---

## 9. Repo layout

```
facechain/
  README.md  ARCHITECTURE.md  pyproject.toml  .env.example
  facechain/
    cli.py  config.py  cache.py
    face/engine.py  face/match.py
    search/base.py  search/lens.py  search/vision.py  search/identity.py
    search/platforms/x.py  search/platforms/youtube.py  search/filters.py  search/rank.py
    evidence/bundle.py
    chain/ipfs.py  chain/memo.py  chain/sas.py  chain/verify.py
  chain-ts/  package.json  sas.ts           # SAS sidecar (sas-lib + @solana/kit)
  samples/                                   # demo input image(s)
  evidence/                                  # run outputs (gitignore all but one sample run)
```

External accounts/keys: **SerpApi key (required, free)**, **Pinata JWT (recommended, free)**, optional Google Cloud Vision key, optional FaceCheck.ID credits. Registry wallet = existing devnet keypair.

---

## 10. Build order (deadline Sept 7, 23:59)

| When | Deliverable |
|---|---|
| Sept 4 (eve) | venv, InsightFace engine + quality gates, Lens client with disk cache, filter + rank table on a test photo |
| Sept 5 (am) | evidence bundle, memo anchor, verify + tamper (pure Python) → **task fully satisfied at this point** |
| Sept 5 (pm) | identity hop (Wikidata → X syndication / YouTube), Pinata pinning |
| Sept 6 (am) | SAS setup + attestation sidecar, `verify --cid`, corroboration logic |
| Sept 6 (pm) | README, `.env.example`, sample run committed, GitHub repo, screen recording, submit |
| Sept 7 | buffer only |

---

## 11. Known limitations (for the README)

- Google Lens does not do face identification; it proposes visually similar images. Face verification on our side is what establishes identity. Works best for people whose photos circulate publicly.
- Instagram, Facebook, TikTok and Reddit no longer allow anonymous content fetch (2025–2026). For those platforms we anchor the post URL plus the engine-served media; for X and YouTube we anchor full post payloads.
- Face similarity thresholds are calibrated on a small set; false accepts/rejects are possible at the review band.
- SerpApi free tier (250/month) bounds the number of fresh searches; responses are cached.
- Devnet only; the registry wallet is a demo key. Responsible use: demo subjects are public figures or consenting users; the tool must not be used to identify private individuals.

---

## 12. Research notes (verified 2026-09-04)

- InsightFace 1.0.1 pure wheel, `buffalo_l` thresholds 0.30–0.45 @ FMR 1e-4..1e-5 — https://pypi.org/project/insightface/ · https://www.insightface.ai/guides/choose-face-recognition-model-and-evaluate
- SerpApi Lens + Image API upload, 250 free/month — https://serpapi.com/google-lens-api · https://serpapi.com/google-lens-upload-an-image · https://serpapi.com/pricing
- SerpApi Yandex reverse image — https://serpapi.com/yandex-reverse-image-api
- Google Vision WEB_DETECTION — https://docs.cloud.google.com/vision/docs/detecting-web
- Bing Search APIs retired 2025-08-11 — https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement
- FaceCheck.ID API + terms — https://facecheck.id/Face-Search/API · https://facecheck.id/Face-Search/Terms
- X oEmbed — https://docs.x.com/x-for-websites/oembed-api ; syndication `tweet-result` endpoint (unofficial, live-tested)
- Wikidata SPARQL — https://query.wikidata.org/sparql
- Reddit public JSON closed 2026 — https://fetchlayer.dev/blog/reddit-api-closed-2026
- solana-py 0.40.x (AsyncClient only) — https://github.com/michaelhly/solana-py/blob/master/CHANGELOG.md · memo cookbook https://michaelhly.com/solana-py/cookbook/transaction-operations/add-memo-to-transaction/
- SPL Memo docs — https://www.solana-program.com/docs/memo
- Solana Attestation Service — https://github.com/solana-foundation/solana-attestation-service · https://solana.com/docs/tools/attestations/overview
- anchorpy stuck on legacy IDL — https://github.com/kevinheavey/anchorpy/issues/147
- Anchor 0.32.x notes — https://www.anchor-lang.com/docs/updates/release-notes/0-32-0
- Pinata upload API — https://docs.pinata.cloud/api-reference/endpoint/upload-a-file
- Devnet faucet — https://faucet.solana.com
