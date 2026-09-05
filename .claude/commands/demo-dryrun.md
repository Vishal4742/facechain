---
description: Dry-run the screen-recording script end to end (cache on) and report timings and anything that would look wrong on camera
allowed-tools: Bash(facechain:*), Bash(sha256sum:*), Bash(solana balance:*), Bash(scripts/demo.sh:*), Read
---

## Context
- Subject image: !`ls samples/*.jpg 2>/dev/null | head -3`
- SerpApi searches remaining: !`test -f .env && grep -q SERPAPI_KEY .env && echo "(checked in run)" || echo "no .env"`
- Wallet: !`solana balance -k ~/.config/solana/id.json -u devnet 2>&1 | tail -1`

## Task
1. Run `scripts/demo.sh --dry` (cache on, no `--live`). Time each step.
2. Check the output for anything that would look wrong on a recording: stack traces, warnings, truncated tables, missing explorer link, a REVIEW instead of ACCEPT, a run longer than 2 minutes.
3. Report a checklist: step | seconds | OK/issue. Suggest fixes; do not apply them.
