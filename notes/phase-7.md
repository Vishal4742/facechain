# Phase 7 — README, sample run, recording, submission

Date: 2026-09-05 (deadline 2026-09-07 23:59)

## State
- `evidence/sample_run/` committed from a real run (Ronaldo): memo tx `2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw`, attestation `v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N`, bundle CID `bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym`, `facechain verify --run evidence/sample_run` → VERIFIED from a clean checkout with no keys.
- `scripts/demo.sh --dry` end to end in ~60 s (cache on). The real take uses `--live` (2 fresh Lens searches, ids printed).
- **Recording done (2026-09-05 04:12 UTC):** `demo/facechain-demo.mp4` (1 min 54 s, 4.4 MB), made with VHS from `scripts/demo.tape` — a live run (SerpApi ids 6a9b96a7…/6a9b96ab…), memo tx `9eKh2uYg…`, attestation `4W5NSrS1…`, VERIFIED then TAMPERED. Frames checked. Recording tooling: `vhs` + `ttyd` in `~/.local/bin`, ffmpeg from apt.
- README covers what / how to run / which chain / limitations (task requirement).

## Recording checklist (used for the take above; re-record with `vhs scripts/demo.tape`)
1. Terminal ≥ 14 pt font, ~120 columns wide, dark theme. `source ~/.venvs/facechain/bin/activate`.
2. Warm-up off camera: `facechain scan --image samples/ronaldo/subject.jpg` (loads the model once).
3. Start recording (Windows: Win+Alt+R, or OBS). Run `scripts/demo.sh` (no `--dry`). It shows:
   face scan → `lens visual_matches … (live id=… at …)` → identity hop → ranked table → ACCEPT line → evidence path + bundle sha256 → memo tx + explorer link → attestation → `sha256sum bundle.json` → VERIFIED → TAMPERED.
4. Open the explorer link in a browser on camera (memo text visible under "Instructions"). Optionally open the winner post URL.
5. Stop recording. Upload (YouTube unlisted / Drive), open the link in an incognito window to confirm it plays.
6. Optional second subject for variety: `DEMO_IMAGE=samples/kohli/subject.jpg scripts/demo.sh --dry` (cached; no extra searches).

## Submission
- Repo: https://github.com/Vishal4742/facechain (make public before submitting: `gh repo edit --visibility public`).
- Form: https://forms.gle/oZbQGuwiNeHVcHWo8 — repo link + recording link. No resubmissions.

## Cut line status
- Shipped: Lens (Path A), identity hop + X (Path B), memo, SAS attestation, Pinata pinning + `verify --cid` (live), tests, CI, README.
- Cut: YouTube Data API, Google Vision, FaceCheck/Yandex, custom Anchor program.

## Native Windows test (2026-09-05 04:50 UTC)
- Windows 11, Python 3.13.12 (`C:\Python313`), Node 26.4, no Solana CLI (keypair file copied to `%USERPROFILE%\.config\solana\id.json`), model pack copied to `%USERPROFILE%\.insightface\models\buffalo_l`, venv `%USERPROFILE%\venvs\facechain-win` with a regular (non-editable) `pip install .`.
- `scripts\smoke.ps1 -Chain -Sas`: doctor OK (cache `C:\Users\...\.cache\facechain`), scan 6.0 s cold, live search ACCEPT 0.88 (Instagram winner; exact_matches returned 0 that time and was correctly not cached), run: pinned media + bundle, memo tx `4fRfp9US…`, VERIFIED, TAMPERED.
- Defect found and fixed: the SAS sidecar path was package-relative, so a regular install looked in `site-packages\chain-ts`. `sidecar_path()` now tries `FACECHAIN_SIDECAR`, the package-relative path, then `chain-ts\sas.ts` in the current directory. Re-run: attestation `CcYmwbmP…` created in 3.8 s, VERIFIED with attestation rows.
- `PYTHONUTF8=1` is required on Windows consoles (emoji in tweet text); `smoke.ps1` sets it.

## Ponytail audit (2026-09-05 05:20 UTC)
- Third technique adopted: the Ponytail plugin (DietrichGebert/ponytail, MIT) installed at project scope (`ponytail@ponytail`, marketplace declared in `.claude/settings.json`); its ladder is now in `CLAUDE.md`.
- Whole-repo audit applied 22 simplifications: `search`/`run` share one option decorator and prelude, `Candidate.to_dict` via `dataclasses.fields`, `_interleave` via `itertools.zip_longest`, `mine_names` via `Counter`, `sas.ts` stdin via `node:stream/consumers`, dead helpers/flags/aliases removed (`test_auth`, `filter_social`, `_registry_pubkey`, `Band`, unused SAS constants, `query_face`), one-liners for dedupe/find_media/emit.
- Net −128 lines (377 deleted, 249 added) across 13 files; ruff, pyright, 132 tests, offline run (ACCEPT, 0 searches) and `verify --run evidence/sample_run` (VERIFIED) unchanged. No `ponytail:` debt markers: every change is an exact equivalent.
- Left alone on purpose: the cache secret-guard tuple, the cached_json/cached_bytes twins, the acceptance/verdict ladders, hashing and tamper code, fixture replay.
