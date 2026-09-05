# facechain

**Give it a photo of a face. It finds a real social-media post showing that face, proves the match with face recognition, and writes a tamper-evident record of the finding to Solana devnet that anyone can re-verify.**

Built for the HH Goa 2026 shortlisting, Task 3 (Face Identification & Blockchain Verification). Demo video, verified sample run and step-by-step verification guide below.

| | |
|---|---|
| Demo video | [demo/facechain-demo.mp4](https://github.com/Vishal4742/facechain/blob/main/demo/facechain-demo.mp4) (1 min 54 s, plain terminal recording of a live run) |
| Sample run to verify | [`evidence/sample_run/`](evidence/sample_run/), anchored as devnet tx [2UZiq877…](https://explorer.solana.com/tx/2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw?cluster=devnet) |
| Verify it without our code | [docs/VERIFY.md](docs/VERIFY.md) |
| Design and research log | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), build notes in [notes/](notes/) |
| Blockchain | Solana devnet: SPL Memo + Solana Attestation Service, details in [Blockchain](#blockchain) |

## Contents

1. [Verify our claim in two minutes](#verify-our-claim-in-two-minutes)
2. [What it does](#what-it-does)
3. [Why the search is genuine](#why-the-search-is-genuine)
4. [Run it yourself](#run-it-yourself)
5. [Commands](#commands)
6. [How verification works](#how-verification-works)
7. [Blockchain](#blockchain)
8. [Evidence format](#evidence-format)
9. [Project layout](#project-layout)
10. [Known limitations](#known-limitations)
11. [FAQ](#faq)
12. [Glossary](#glossary)
13. [Responsible use, credits, license](#responsible-use)

## Verify our claim in two minutes

No API keys, no wallet, no model download. Only Python 3.12+ and the public devnet RPC.

```bash
git clone https://github.com/Vishal4742/facechain && cd facechain
python3 -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
facechain verify --run evidence/sample_run
```

Expected: a table headed **VERIFIED** showing the bundle hash `a8f1e58b…6758c3`, the memo transaction `2UZiq877…`, `signer ok: yes`, and the on-chain memo text containing `h=a8f1e58b…`. Then break it on purpose:

```bash
facechain verify --run evidence/sample_run --tamper
```

Expected: **TAMPERED**. One byte of the stored post image was flipped; its hash no longer matches the hash committed on chain. Exit code 1.

Prefer not to trust our code at all? [docs/VERIFY.md](docs/VERIFY.md) does the same check with `sha256sum`, `curl` against the Solana JSON-RPC and an IPFS gateway.

## What it does

```
 photo ──► InsightFace (SCRFD detector + ArcFace embedder) ──► 512-d face embedding
              │
              ├─ Path A  Google Lens (via SerpApi): visual + exact matches ─────┐
              └─ Path B  Lens identity hint → Wikidata verified handles          │  candidates
                         → the person's own X posts (public syndication feed) ──┘
                                                    │
                    download each candidate's media → detect faces → cosine vs query
                    → quality gate → ranked table → ACCEPT (with corroboration) / REVIEW
                                                    │
                    evidence bundle (canonical JSON, integers only) → H = sha256(bundle)
                    ├─ IPFS (Pinata): bundle + post media pinned, CIDs recorded
                    ├─ Solana devnet, SPL Memo: "FACECHAIN/1 h=H media=… cid=… sim=… url=…"
                    └─ Solana devnet, Attestation Service: record whose address derives from H
                                                    │
                    verify: re-hash the stored files → find the memo by H → check the attestation
                    verify --tamper: flip one byte → TAMPERED, attestation ABSENT
```

Five stages, each visible in the terminal:

1. **Scan.** Detect faces in the input photo, pick the query face (largest, or `--face-index`), compute a 512-dimensional ArcFace embedding. Quality gates on detection score, eye distance and blur.
2. **Search.** Path A uploads the photo to Google Lens through SerpApi and collects visual and exact matches, each with a link and a thumbnail. Path B takes the identity hint Lens returns, resolves the person on Wikidata (humans only, label must match), reads their verified handles, and pulls their own recent X posts that carry media. Both paths run live; every SerpApi search id and timestamp is printed.
3. **Verify by face.** For every candidate, download the media, detect faces, and compute the cosine similarity to the query embedding. The ranked table shows engine, platform, URL, faces found, similarity, band and corroboration.
4. **Decide.** The winner is the best-scoring social **post** (never a profile page) at or above the match threshold, and it is only accepted with corroboration: a second candidate at 0.40 or above, or the post being authored by the identity Wikidata resolved. Otherwise the result is REVIEW and nothing is anchored.
5. **Record and verify.** The finding is written to an evidence bundle, pinned to IPFS, and committed to Solana devnet twice: a memo carrying the hashes, and an attestation whose address is derived from the bundle hash. `verify` recomputes everything from the stored files and checks it against the chain.

## Why the search is genuine

- Nothing is looked up in a table. Two Lens calls happen per run, and their SerpApi ids and timestamps are printed and stored in `search.json`.
- The whole ranked candidate list is printed, including the rejected ones, so the decision is visible.
- Lens proposes; faces decide. A private person's photo returns no Lens results at all, and the pipeline answers REVIEW instead of inventing a match (we tested this on a non-public face: zero candidates, nothing anchored).
- Different input, different answer: the same code found an Instagram post for Ronaldo, a YouTube post for Kohli and a Pinterest pin for Hamilton, chosen by the rule, not by hand.
- Cached responses are used only to save quota during development. On camera, `--live` forces fresh calls; if a live call ever fails, a recorded response is replayed **with a red banner** naming the failure, and the chain step is always live.

## Run it yourself

Tested on Linux, WSL2 and native Windows 11. Python 3.12+, about 1 GB of disk for the face model. Node ≥ 22.6 only for the optional attestation step.

```bash
git clone https://github.com/Vishal4742/facechain && cd facechain
python3 -m venv ~/.venvs/facechain && . ~/.venvs/facechain/bin/activate   # on WSL keep the venv on the Linux filesystem
pip install -e ".[dev]"

# face model (InsightFace buffalo_l, ~330 MB): download once, unzip, expect 5 .onnx files
mkdir -p ~/.insightface/models/buffalo_l
curl -L -o /tmp/buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -o /tmp/buffalo_l.zip -d ~/.insightface/models/buffalo_l

cp .env.example .env         # fill in SERPAPI_KEY; PINATA_JWT is optional; the demo attestation ids are pre-filled
facechain doctor --online    # checks model, keys, wallet, devnet balance, cache directory

facechain run --image samples/ronaldo/subject.jpg --engines lens,identity        # search + evidence + devnet memo
(cd chain-ts && npm ci)      # optional: attestation sidecar; then add --sas to run/anchor
```

| What you need | For | Where |
|---|---|---|
| `SERPAPI_KEY` | the Google Lens search | free plan at serpapi.com, 250 searches a month; a run costs 2 |
| Solana devnet keypair with a little SOL | signing the memo (and attestation) | `solana-keygen new`, then faucet.solana.com; path in `SOLANA_KEYPAIR_PATH` |
| `PINATA_JWT` (optional) | pinning bundle and media to IPFS | free plan at pinata.cloud |
| `SAS_CREDENTIAL`, `SAS_SCHEMA` (pre-filled) | checking attestations of the demo runs | run `facechain setup-sas` only to attest with your own wallet |

**Native Windows** (PowerShell, tested with Python 3.13 and Node 26): create a venv, `pip install .`, unzip the model into `%USERPROFILE%\.insightface\models\buffalo_l`, put a devnet keypair at `%USERPROFILE%\.config\solana\id.json`, set `$env:PYTHONUTF8 = "1"` (post text contains emoji), then `scripts\smoke.ps1 -Chain -Sas` runs doctor, scan, live search, run, verify and the tamper test. The bash scripts and the video recording tape are Linux/WSL only.

## Commands

```bash
facechain scan   --image PHOTO                          # faces found, quality, which one is the query
facechain search --image PHOTO --engines lens,identity  # ranked candidates and the ACCEPT/REVIEW decision, nothing written to chain
facechain run    --image PHOTO --engines lens,identity  # search → evidence/<run_id>/ → IPFS → devnet memo
facechain run    --image PHOTO --engines lens,identity --sas   # … plus the attestation
facechain anchor --run evidence/<run_id> [--sas]        # (re)anchor an existing bundle
facechain attest --run evidence/<run_id>                # add an attestation to a run anchored earlier
facechain verify --run evidence/<run_id>                # re-hash evidence, find memo and attestation → VERIFIED?
facechain verify --run evidence/<run_id> --tamper       # flip one byte of the media → TAMPERED
facechain verify --cid <bundle CID>                     # fetch bundle and media from IPFS, then verify
facechain setup-sas                                     # create your own attestation credential + schema (one time)
facechain doctor --online                               # environment check
```

Flags: `--live` bypasses cached search reads (used on camera). `--offline` never touches the network. `--no-anchor` stops after writing evidence; `--no-pin` skips IPFS. `--face-index N` picks a face when the photo has several. `--registry PUBKEY` verifies records signed by another wallet.

Exit codes: `0` accepted or verified · `1` verification failed · `2` no face, or the match was not accepted (REVIEW) · `3` a search engine failed.

Every run writes `evidence/<run_id>/`: `query.jpg`, `candidates.json` (the full ranked table), `post_media.jpg` (the winning post's image exactly as downloaded), `post.json`, `search.json` (search ids, identity, decision), `bundle.json` (the hashed object) and, after anchoring, `receipt.json` (signatures, addresses, CIDs).

## How verification works

1. `bundle.json` is canonical JSON: sorted keys, no whitespace, UTF-8, integers only (similarity is stored in basis points, so 0.8777 becomes 8777). Its SHA-256 is **H**. The file on disk holds exactly the hashed bytes, so `sha256sum bundle.json` prints H.
2. The **memo transaction**, signed by the registry wallet, carries `FACECHAIN/1 h=<H> media=<sha256 of post_media.jpg> cid=<bundle CID or -> sim=<bps> url=<post url>`.
3. The **attestation** (Solana Attestation Service) stores `{bundle_hash, cid, post_url, similarity_bps}` at an address derived from H itself: `PDA("attestation", credential, schema, H)`. Anyone holding `bundle.json` can compute where the record must be, without a receipt.
4. `facechain verify` re-hashes the stored files, scans the registry wallet's transactions for a memo containing `h=<H>`, checks the signer and compares the media hash in the memo with the file on disk, then derives the attestation address, fetches it and compares every field. Nothing is re-downloaded: the verdict depends only on what is stored and what is on chain.
5. **Tamper test.** `verify --tamper` copies the run and flips the middle byte of `post_media.jpg`. The memo is still found, but the media hash no longer matches → **TAMPERED**. The attestation is derived from the evidence as it now is, so it comes back **ABSENT**: nobody attested that evidence.

Trust model: a record is trusted only when the registry wallet signed it. `verify` uses the registry recorded in the receipt when it is the demo registry, and warns otherwise; pass `--registry` explicitly for other wallets.

## Blockchain

| Item | Value |
|---|---|
| Network | Solana devnet, `https://api.devnet.solana.com` |
| Record 1 | SPL Memo program `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`, one transaction per accepted match, fee 5000 lamports |
| Record 2 | [Solana Attestation Service](https://github.com/solana-foundation/solana-attestation-service) program `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG` |
| Credential | `Awhv5DjjmeeGZPxeMim1hW8yWKgMJtUFD2dX7BrArpzh` (`FACECHAIN`) |
| Schema | `DNnsTXgmuPDsb3gKF8rgYsnRYP7h6qLEMC9udtxofpDD` (`FaceMatchV1`: `bundle_hash`, `cid`, `post_url`, `similarity_bps`) |
| Registry wallet | `9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX` (demo key) |
| Attestation client | `chain-ts/sas.ts` (`sas-lib` + `@solana/kit`), called from Python over JSON |

Committed sample run, `evidence/sample_run/` (Cristiano Ronaldo, Instagram post, similarity 0.8777, 40 candidates verified):

| | |
|---|---|
| Bundle hash H | `a8f1e58be5945cbddff36479a669b26fcb080d4dfb09623791a0a4fa946758c3` |
| Memo tx | [`2UZiq877N8gc…pqBdihw`](https://explorer.solana.com/tx/2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw?cluster=devnet) |
| Attestation | [`v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N`](https://explorer.solana.com/address/v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N?cluster=devnet), created by tx `4VoPki5Q…` |
| Bundle on IPFS | `bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym` |
| Post media on IPFS | `bafkreie5gwsu3egkxodd5xwxmq5xdpqjuvxk3b4qvujwakyufuzhkj7duu` |
| Lens search ids | `6a9b8ad26539a2e75723d28b`, `6a9b8ad7f30d1363c7ab2709` (2026-09-05 03:21 UTC) |

Why two records: the memo is the simplest possible commitment and is readable in any explorer; the attestation is the Solana Foundation's standard for exactly this kind of claim and makes the record addressable from the bundle hash alone. Either one satisfies the task on its own.

## Evidence format

```json
{
  "version": 1,
  "query": {"face_id": "<sha256 of the query image>", "detector": "scrfd_10g", "embedder": "arcface_r50_buffalo_l"},
  "post":  {"url": "https://www.instagram.com/p/Db6Jg25gffC", "platform": "instagram", "author": null, "title": "...",
            "text": null, "media_url": "...", "media_sha256": "9d35a54d…", "media_cid": "bafkreie5…",
            "text_sha256": null, "fetched_at": 1788579613},
  "match": {"engine": "lens:visual", "similarity_bps": 8777, "threshold_bps": 4500, "candidates_considered": 40,
            "corroborated_by": [], "engines": ["lens", "identity"]}
}
```

Only integers, strings, booleans, null, lists and objects may enter the bundle; floats and git commit ids are rejected so that a rebuild never changes H.

## Project layout

```
facechain/
  cli.py, cli_chain.py     commands: scan, search, run | anchor, attest, verify, setup-sas
  pipeline.py              orchestration: scan → search → verify faces → decide
  face/                    engine.py (InsightFace), match.py (cosine, bands, quality gate)
  search/                  lens.py (SerpApi Lens), identity.py (Wikidata), platforms/x.py,
                           filters.py (URL rules), media.py (downloads), rank.py (scoring, acceptance)
  evidence/bundle.py       canonical JSON, hashing, run directory, tamper copy
  chain/                   memo.py (SPL Memo), sas.py (attestation sidecar glue), ipfs.py (Pinata), verify.py
  cache.py, http.py        content-addressed cache, single HTTP entry point (secrets redacted)
chain-ts/sas.ts            attestation sidecar (Node, sas-lib + @solana/kit)
evidence/sample_run/       the committed, verifiable run
samples/                   CC-licensed photos of the demo subjects + impostors (samples/SOURCES.md)
scripts/                   smoke.sh / smoke.ps1, demo.sh + demo.tape (video), calibrate.py, fetch_samples.py
tests/                     132 tests; fixtures under tests/fixtures/cache make the pipeline runnable offline
docs/, notes/              architecture and research log; per-phase build notes with real outputs
```

Development: `pytest -q`, `ruff check . && ruff format --check .`, `pyright`, `npx tsc --noEmit -p chain-ts`, `scripts/smoke.sh` (add `SMOKE_CHAIN=1` for a devnet round trip). The repository also carries the engineering harness it was built with: `CLAUDE.md`, Claude Code commands and agents under `.claude/`, ECC rules, and the Ponytail plugin.

## Known limitations

- **Public figures only, in practice.** Google Lens does not identify faces; it proposes visually similar images, and it returns nothing for close-up faces of people it does not treat as public. Our face verification establishes identity among what Lens proposes. A private person yields REVIEW.
- **Platform access.** Instagram, Facebook, TikTok and Reddit refuse anonymous content fetches. For those platforms the anchored media is the image the search engine served for the post; for X and YouTube the original media and text are fetched. Supported platforms: Instagram, X, Facebook, TikTok, Threads, YouTube, LinkedIn, Pinterest, Reddit.
- **Thresholds** were calibrated on three public figures and six impostors: impostor similarity never exceeded 0.19; same-person pairs ranged 0.44–0.84 at full size and dipped to 0.26 for one subject at 150 px thumbnails. Match needs ≥ 0.45 plus corroboration; 0.35–0.45 is REVIEW and is never anchored. Calibration table for the Kohli set:

| pairs | n | min | median | max |
|---|---|---|---|---|
| same person, full size | 10 | 0.530 | 0.712 | 0.836 |
| same person, 150 px thumbnail vs full | 20 | 0.498 | 0.684 | 0.833 |
| impostor, full size | 30 | −0.058 | 0.037 | 0.155 |
| impostor, 150 px thumbnail | 30 | −0.063 | 0.040 | 0.152 |

- **Illustrated faces.** The detector also finds drawn faces, and identical artwork matches itself strongly; the pipeline reports what it finds and does not judge whether a face is a photograph.
- **Quota.** SerpApi's free plan allows 250 searches a month; a fresh run costs two, re-runs of the same photo cost none. Google's result counts vary between calls (exact matches for the same photo returned 378 once and 0 an hour later); empty results are never cached.
- **Devnet only.** The registry key is a demo key; the memo is a hash commitment, not a legal attestation. Input is an image file; no webcam capture.
- **Honesty about the demo.** Candidate photos were tested during development to choose the subject; the winner in every run is chosen by the rule, never by hand. The committed sample run replays the recorded live search of 2026-09-05 03:21 UTC (`search.json` shows the ids and `live: false`); the video was recorded with `--live`.

## FAQ

**Is the match really based on the face?** Yes. Lens only proposes pages. Every candidate's image is downloaded and its faces embedded; the similarity to the query face is what ranks and decides. Look-alikes and unrelated pages sit far below the threshold.

**Why Google Lens and not a face-search engine?** Lens is official, cheap and works through a documented API; face-native engines are paid, crypto-only, or against their own terms. Bing Visual Search was retired in 2025 and TinEye only finds identical images.

**Why devnet?** The task allows any chain; devnet is free and public, so anyone can re-verify without spending anything. The code takes an RPC URL, so mainnet is a config change.

**What if IPFS is down?** Verification never depends on the CID. The repo carries the evidence; `--cid` is an extra route.

**What if the registry key leaks?** A leaked key could sign new false records; existing records are unaffected, since their hashes are committed. Rotate the key and change the trusted registry.

**Can it find me?** Only if photos of you are publicly indexed. For most people it returns no candidates and stops at REVIEW.

## Glossary

- **Embedding**: a 512-number vector describing a face; similar faces have a cosine similarity near 1, unrelated faces near 0.
- **Candidate**: a page or post proposed by a search engine, with the image it showed for it.
- **Band**: `match` (≥ 0.45), `review` (0.35–0.45), `reject`, `no face`, `no media`.
- **Corroboration**: a second, independent signal that the identity is right: another candidate ≥ 0.40, or the post's author being the resolved identity.
- **Bundle / H**: the canonical JSON describing the finding, and its SHA-256, which is what goes on chain.
- **Memo**: an SPL Memo transaction carrying H and the media hash, signed by the registry wallet.
- **Attestation / PDA**: a Solana Attestation Service account whose address is derived from H (a program-derived address), holding the same facts.
- **Registry wallet**: the keypair whose signature makes a record trustworthy.
- **CID**: the content identifier of a file pinned to IPFS.

## Responsible use

This tool can identify people from a photo. The demo uses public figures photographed at public events (licences in `samples/SOURCES.md`). Do not use it to identify private individuals without their consent; the search engines involved have their own terms of service, and several jurisdictions regulate biometric identification.

## Credits

InsightFace (buffalo_l models, non-commercial research licence), SerpApi, Wikidata, Pinata, the Solana Attestation Service and `sas-lib`, solana-py and solders, VHS for the recording. Sample photos from Wikimedia Commons contributors named in `samples/SOURCES.md`.

## License

MIT.
