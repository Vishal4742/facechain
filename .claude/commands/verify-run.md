---
description: Anchor an evidence run on devnet, verify it, then run the tamper test; report with signatures and hashes
argument-hint: <evidence run dir, e.g. evidence/20260905T101500Z-ab12>
allowed-tools: Bash(facechain:*), Bash(sha256sum:*), Bash(solana balance:*), Bash(solana confirm:*), Read
---

## Context
- Run dir: $ARGUMENTS
- Bundle present: !`test -f "$ARGUMENTS/bundle.json" && echo yes || echo NO`
- Wallet: !`solana balance -k ~/.config/solana/id.json -u devnet 2>&1 | tail -1`

## Task
1. `sha256sum $ARGUMENTS/bundle.json` and note the hash H.
2. If `$ARGUMENTS/receipt.json` is missing: `facechain anchor --run $ARGUMENTS`.
3. `facechain verify --run $ARGUMENTS` — must print VERIFIED and a signature whose memo contains `h=<H>`.
4. `facechain verify --run $ARGUMENTS --tamper` — must print TAMPERED.
5. Report: H, signature, slot, block time, explorer link, and both verdicts, quoting the actual output lines.
