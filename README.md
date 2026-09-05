# facechain

Face scan → genuine social-media search → face-verified match → tamper-evident record on Solana devnet → independent re-verification.

Built for the HH Goa 2026 shortlisting Task 3. Work in progress; see `docs/ARCHITECTURE.md` for the design and `notes/` for build progress.

## On-chain records (devnet)

Every accepted match is anchored twice from the registry wallet `9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX`:

1. an SPL Memo `FACECHAIN/1 h=<bundle sha256> media=… cid=… sim=… url=…` (pure Python), and
2. with `--sas`, a [Solana Attestation Service](https://github.com/solana-foundation/solana-attestation-service) attestation whose nonce **is** the bundle hash, so anyone can derive the attestation address from `bundle.json` alone — no receipt needed.
   Credential `Awhv5DjjmeeGZPxeMim1hW8yWKgMJtUFD2dX7BrArpzh` (`FACECHAIN`), schema `DNnsTXgmuPDsb3gKF8rgYsnRYP7h6qLEMC9udtxofpDD` (`FaceMatchV1`: `bundle_hash`, `cid`, `post_url`, `similarity_bps`).

```bash
cd chain-ts && npm ci && cd ..          # sidecar deps (Node >= 22.6): sas-lib 1.0.10 + @solana/kit 5.5.1
facechain setup-sas                     # once: credential + schema, addresses written to .env
facechain run --image photo.jpg --sas   # memo + attestation; or: facechain anchor --run DIR --sas
facechain attest --run DIR              # attest a run that was anchored before
facechain verify --run DIR [--tamper]   # re-hash, memo scan, derive the attestation PDA and compare
```

`verify --tamper` flips one byte of the stored media: the media hash no longer matches the bundle and the attestation PDA derived from the evidence on disk is absent.
