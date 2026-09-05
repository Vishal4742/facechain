# Phase 7 — README, sample run, recording, submission

Date: 2026-09-05 (deadline 2026-09-07 23:59)

## State
- `evidence/sample_run/` committed from a real run (Ronaldo): memo tx `2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw`, attestation `v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N`, bundle CID `bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym`, `facechain verify --run evidence/sample_run` → VERIFIED from a clean checkout with no keys.
- `scripts/demo.sh --dry` end to end in ~60 s (cache on). The real take uses `--live` (2 fresh Lens searches, ids printed).
- README covers what / how to run / which chain / limitations (task requirement).

## Recording checklist (plain screen recording, no editing needed)
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
