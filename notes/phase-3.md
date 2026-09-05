# Phase 3 — Evidence bundle + memo anchor + verify/tamper

Date: 2026-09-05

## Built
- `evidence/bundle.py` — run ids (`%Y%m%dT%H%M%SZ-<4hex>`), canonical bytes, `bundle_hash`, `assert_hashable` (ints/strings only, floats rejected), `build_bundle` (query/post/match sections, no git commit), `write_evidence` (query, candidates.json, post_media.<ext>, post.json, bundle.json = exact canonical bytes), `verify_local` (re-hash stored files, never re-download), `tamper_copy` (flip the middle byte of the media).
- `chain/memo.py` — memo text `FACECHAIN/1 h=… media=… cid=… sim=… url=…` (≤ 500 bytes, URL truncated last), regex parser that accepts the `[len] ` prefix from `getSignaturesForAddress`, `send_memo` (one-shot build/sign/send with one retry on blockhash/429), `find_memo` (wallet scan at confirmed commitment with a short retry), `tx_memo` (jsonParsed lookup: signer, slot, blockTime).
- `chain/verify.py` — VERIFIED / TAMPERED / UNANCHORED verdicts; wallet scan first, receipt signature as a secondary route; rich report.
- `cli_chain.py` — `facechain run` (search → evidence → memo), `facechain anchor --run DIR`, `facechain verify --run DIR|--bundle FILE [--tamper]`.

## Verified (real output, devnet)
- Synthetic bundle `evidence/_synthetic` (real Kohli media bytes, fake post URL): `sha256sum bundle.json` = `f91da8318337be538a8f07ecfeb85f5063955d9de0fabe66aa9ba3c49b9cafb0` = `h=` in the memo.
- `facechain anchor` → tx `5RHpH7BMJ3h2K1YmozsGc6T53swmZyHDKD6tCWFWRtCTEpzzoA75QQWjEpcwBXjjrfirTTyMe3BHHZ9LLPCZStqn`, slot 493330709, 2026-09-05 02:48:32 UTC, fee 5000 lamports, memo 218 bytes.
- `facechain verify --run evidence/_synthetic` → **VERIFIED** (memo found via wallet scan, signer 9ziKFvAU…a1MX ok), exit 0.
- `facechain verify --run evidence/_synthetic --tamper` → **TAMPERED** (media sha256 mismatch; memo still found), exit 1.
- 93 tests pass; ruff and pyright clean.

## Decisions
- Memo-only anchoring satisfies the task; SAS attestation stays Phase 6 (separate transaction).
- Verification does not need the receipt: the wallet scan finds the record from the bundle hash alone. The receipt signature is only a fallback for the seconds right after anchoring.
- First run right after `anchor` showed UNANCHORED because `getSignaturesForAddress` defaulted to finalized commitment; fixed with `commitment=Confirmed` + 3 attempts.

## Open
- The end-to-end `facechain run` on a real photo still needs the SerpApi key (live Lens).
- `evidence/_synthetic*` are gitignored scratch runs; the committed sample run comes from a real Lens search in Phase 7.

## Next phase needs
- Phase 4: fixture export from the first real run, `scripts/smoke.sh`, unit tests for memo/verify glue.
