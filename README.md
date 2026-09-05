# facechain

**Face scan → genuine social-media search → face-verified match → tamper-evident record on Solana devnet → independent re-verification.**

Built for the HH Goa 2026 shortlisting, Task 3 (Face Identification & Blockchain Verification).

```
 photo ──► InsightFace (SCRFD + ArcFace) ──► 512-d face embedding
              │
              ├─ Path A  Google Lens (SerpApi): visual + exact matches ──┐
              └─ Path B  Lens identity hint → Wikidata verified handles  │  candidates
                         → X syndication timeline (posts with media) ───┘
                                                    │
                          download media → detect faces → cosine vs query
                          → quality gate → ranked table → ACCEPT / REVIEW
                                                    │
                     evidence bundle (canonical JSON, ints only) → H = sha256
                     ├─ IPFS (Pinata, optional)  → CID
                     ├─ Solana devnet: SPL Memo  h=H media=… cid=… sim=… url=…
                     └─ Solana devnet: SAS attestation, nonce = H (--sas)
                                                    │
                     verify: re-hash stored files → wallet scan for h=H
                             → derive attestation PDA from H → VERIFIED
                     verify --tamper: flip one byte → TAMPERED, attestation ABSENT
```

Reverse image search only *proposes* pages. What decides is the ArcFace similarity between the scanned face and the faces inside each candidate's media, plus corroboration (a second candidate above 0.40, or the post being authored by the identity Wikidata resolved). That is what makes this face identification rather than duplicate-image lookup, and every candidate with its score is printed so the search is visibly real.

## Demo

Screen recording: _link to be added at submission_.

## Quickstart

Linux or WSL2, Python 3.12, about 1 GB of disk for the face model. Node ≥ 22.6 (24 tested) is only needed for the optional attestation sidecar.

```bash
git clone https://github.com/Vishal4742/facechain && cd facechain
python3 -m venv ~/.venvs/facechain && source ~/.venvs/facechain/bin/activate   # keep the venv on a Linux filesystem
pip install -e ".[dev]"

# face model (InsightFace buffalo_l, ~330 MB): download once, unzip, expect 5 .onnx files
mkdir -p ~/.insightface/models/buffalo_l
curl -L -o /tmp/buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -o /tmp/buffalo_l.zip -d ~/.insightface/models/buffalo_l

cp .env.example .env        # then fill in SERPAPI_KEY (required), PINATA_JWT (optional)
facechain doctor --online   # model, keys, wallet, devnet balance

(cd chain-ts && npm ci)     # optional: SAS sidecar deps (sas-lib 1.0.10 + @solana/kit 5.5.1)
facechain setup-sas         # optional, once: SAS credential + schema; addresses written to .env
```

Keys and accounts:

| What | Needed for | Where |
|---|---|---|
| `SERPAPI_KEY` | Google Lens search (Path A) | free plan at serpapi.com, 250 searches/month |
| `PINATA_JWT` | pinning the evidence to IPFS (optional) | free plan at pinata.cloud |
| Solana keypair | signing the devnet memo and attestation | `solana-keygen new`, fund at faucet.solana.com; path in `SOLANA_KEYPAIR_PATH` |
| `SAS_CREDENTIAL`, `SAS_SCHEMA` | the attestation record (optional) | written by `facechain setup-sas` |

## Commands

```bash
facechain scan   --image samples/kohli/subject.jpg                 # faces, quality, which face is the query
facechain search --image samples/kohli/subject.jpg --engines lens,identity   # ranked candidates, ACCEPT/REVIEW
facechain run    --image samples/kohli/subject.jpg --engines lens,identity   # search + evidence bundle + devnet memo
facechain run    --image samples/kohli/subject.jpg --engines lens,identity --sas   # ... + SAS attestation
facechain anchor --run evidence/<run_id> [--sas]                    # (re)anchor an existing bundle
facechain attest --run evidence/<run_id>                            # attest a run anchored earlier (no new memo)
facechain verify --run evidence/<run_id>                            # re-hash evidence, memo + attestation, VERIFIED?
facechain verify --run evidence/<run_id> --tamper                   # flip one byte of the media → TAMPERED
facechain verify --cid <bundle CID>                                 # third-party check from IPFS alone
facechain setup-sas                                                 # one-time SAS credential + schema
```

Flags: `--live` bypasses cached search reads so every Lens call is fresh (used on camera; SerpApi's search id and timestamp are printed). `--offline` never touches the network. `--no-anchor` and `--no-pin` skip the chain and IPFS steps. `--sas` adds the attestation transaction after the memo (refuses to start until `setup-sas` has run).

Exit codes: `0` accepted / verified, `1` verification failed, `2` no face or the match was not accepted (REVIEW), `3` an engine failed.

## How verification works

1. `facechain run` writes `evidence/<run_id>/` with `query.jpg`, `candidates.json` (the whole ranked table), `post_media.jpg` (the matched post's image exactly as downloaded), `post.json`, and `bundle.json`.
2. `bundle.json` is canonical JSON (sorted keys, no whitespace, UTF-8, integers only: similarity is stored in basis points). Its SHA-256 is **H**. Because the file holds exactly the hashed bytes, `sha256sum bundle.json` prints H.
3. The memo transaction, signed by the registry wallet, carries `FACECHAIN/1 h=<H> media=<sha256 of post_media> cid=<bundle CID or -> sim=<bps> url=<post url>`.
4. With `--sas`, a second transaction creates a Solana Attestation Service record `{bundle_hash, cid, post_url, similarity_bps}` whose nonce **is** H, so the attestation address is derivable from `bundle.json` alone: `PDA("attestation", credential, schema, H)`.
5. `facechain verify` re-hashes the stored files, scans the registry wallet's signatures for a memo containing `h=<H>`, reads the transaction, checks the signer, and compares the media hash in the memo with the file on disk. When SAS is configured it also derives the attestation PDA, fetches it and checks the signer and every field against the bundle. Nothing is re-downloaded, so the verdict depends only on what is stored and what is on chain.
6. Anyone can repeat step 5 with just `bundle.json`, `post_media.jpg`, the registry public key and a public devnet RPC. With Pinata configured, `verify --cid` fetches both files from IPFS first.

Tamper demo: `verify --tamper` copies the run, flips the middle byte of `post_media.jpg`, and re-verifies. The memo is still found, but the media hash no longer matches → **TAMPERED**. The attestation PDA is derived from the evidence as it is on disk (the bundle re-hashed with the actual media digest), so it comes back **ABSENT**: nobody ever attested that evidence.

## Blockchain

- **Network:** Solana devnet (`https://api.devnet.solana.com`).
- **Record 1:** SPL Memo program `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`, one transaction per accepted match, fee 5000 lamports.
- **Record 2 (`--sas`):** [Solana Attestation Service](https://github.com/solana-foundation/solana-attestation-service) program `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG`; credential `Awhv5DjjmeeGZPxeMim1hW8yWKgMJtUFD2dX7BrArpzh` (`FACECHAIN`), schema `DNnsTXgmuPDsb3gKF8rgYsnRYP7h6qLEMC9udtxofpDD` (`FaceMatchV1`: `bundle_hash`, `cid`, `post_url`, `similarity_bps`), one attestation per bundle with nonce = H, no expiry. Built with `sas-lib` + `@solana/kit` in `chain-ts/sas.ts`, driven from Python over JSON.
- **Registry wallet:** `9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX` (demo key; a record is only trusted when this key signed it).
- **Committed sample run** (`evidence/sample_run/`, Cristiano Ronaldo, Instagram winner at similarity 0.88): memo tx [2wRJXvnM…](https://explorer.solana.com/tx/2wRJXvnMAH9h6ZG9oXAa741mGtpkb3LwF35BdsVWm6rVogVzsciHfuA?cluster=devnet), attestation PDA `5CiaguKGCsZafw9ofKenFbHS2qoNQJ2qeU3h38cKCD8c`. Re-verify it yourself: `facechain verify --run evidence/sample_run` (needs only the public devnet RPC).

## Evidence bundle

```json
{
  "version": 1,
  "query": {"face_id": "<sha256 of the query image>", "detector": "scrfd_10g", "embedder": "arcface_r50_buffalo_l"},
  "post": {"url": "...", "platform": "x", "author": "@handle", "title": null, "text": "...",
           "media_url": "...", "media_sha256": "...", "media_cid": null, "text_sha256": "...", "fetched_at": 1757000000},
  "match": {"engine": "lens:visual", "similarity_bps": 7123, "threshold_bps": 4500,
            "candidates_considered": 37, "corroborated_by": ["identity:@handle"], "engines": ["lens", "identity"]}
}
```

## Caching, quotas and live-proof

Every network response is cached under `~/.cache/facechain`, keyed by a hash of the request that never includes secrets or the short-lived upload id. Development iterations therefore cost no SerpApi quota. On camera, `--live` forces fresh Lens calls and prints SerpApi's `search_metadata.id` and `created_at`. If a live call fails, a recorded response is replayed **with a red banner naming the error**; the chain step is always live. X's syndication timeline is rate-limited (about 30 calls per 15 minutes), so it is always served from cache once fetched.

## Development

The repo carries its engineering harness: `CLAUDE.md`, per-phase notes in `notes/`, ECC rules under `.claude/rules/ecc`, custom commands and agents under `.claude/`. Tests are written before implementations for the pure modules.

```bash
pytest -q --cov=facechain          # 100+ tests; model-backed tests skip without the model pack
ruff check . && ruff format --check . && pyright
npx tsc --noEmit -p chain-ts       # typecheck the SAS sidecar
scripts/smoke.sh                   # checks + tests + offline pipeline; SMOKE_CHAIN=1 adds a devnet round trip
python scripts/calibrate.py --pos samples/kohli --neg samples/neg --markdown
```

## Known limitations

- Google Lens does not identify faces; it proposes visually similar images. The face verification on our side establishes identity, so the pipeline works best for people whose photos circulate publicly. A private individual with no indexed photos yields REVIEW, not a match.
- Instagram, Facebook, TikTok and Reddit no longer allow anonymous content fetches. For those platforms the anchored media is the image the search engine served for the post; for X and YouTube the original media and text are fetched.
- Thresholds were calibrated on three public figures and six impostors (below). Impostor similarity never exceeded 0.19; same-person pairs ranged 0.44–0.84 at full size and dipped to 0.26 for one subject at 150 px thumbnails. Matches need ≥ 0.45 plus corroboration; 0.35–0.45 is shown as REVIEW and never anchored.

| pairs (Kohli) | n | min | median | max |
|---|---|---|---|---|
| same person, full size | 10 | 0.530 | 0.712 | 0.836 |
| same person, 150 px thumbnail vs full | 20 | 0.498 | 0.684 | 0.833 |
| impostor, full size | 30 | -0.058 | 0.037 | 0.155 |
| impostor, 150 px thumbnail | 30 | -0.063 | 0.040 | 0.152 |

- SerpApi's free plan allows 250 searches a month; responses are cached so a fresh run costs two searches.
- Input is an image file. Webcam capture is not wired in (WSL2 has no camera access by default).
- Devnet only; the registry key is a demo key and the memo is a hash commitment, not a legal attestation.
- Candidate photos were tested during development to choose the demo subject; the winner in every run is chosen by the rule above, never by hand.

## Responsible use

This tool can identify people from a photo. The demo uses public figures photographed at public events (see `samples/SOURCES.md` for licences). Do not use it to identify private individuals without their consent; the search engines involved have their own terms of service, and several jurisdictions regulate biometric identification.

## Sample images

All sample photos come from Wikimedia Commons under the licences listed in `samples/SOURCES.md`.

## License

MIT.
