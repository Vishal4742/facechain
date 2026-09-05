# Verify the sample run without trusting our code

Everything below uses only `sha256sum`, `curl`, `python3` (standard library) and public endpoints. It checks the committed run in `evidence/sample_run/` against Solana devnet and IPFS. Expected values are quoted so you can compare by eye.

The claim being verified: on 2026-09-05 a face search accepted the Instagram post `https://www.instagram.com/p/Db6Jg25gffC` as showing the scanned face, and the evidence of that finding was committed on chain **before** anyone could alter it.

## 1. Hash the evidence

```bash
cd evidence/sample_run
sha256sum bundle.json post_media.jpg
```

Expected:

```
a8f1e58be5945cbddff36479a669b26fcb080d4dfb09623791a0a4fa946758c3  bundle.json
9d35a54d90cabb863eded7643b71be09a56ead8790ad13602b142d327527e3a5  post_media.jpg
```

`bundle.json` is stored as the exact bytes that were hashed, so its digest is **H**. Confirm the bundle names that media hash and that post:

```bash
python3 -c "import json; b=json.load(open('bundle.json')); print(b['post']['media_sha256']); print(b['post']['url']); print(b['match']['similarity_bps'])"
```

Expected: `9d35a54d…7527e3a5`, the Instagram URL, and `8777` (similarity 0.8777).

## 2. Read the memo from Solana devnet

Fetch the transaction named in `receipt.json` straight from the public RPC:

```bash
SIG=2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw
curl -s https://api.devnet.solana.com -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getTransaction","params":["'$SIG'",{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; m=r['transaction']['message']; print('signer:', m['accountKeys'][0]['pubkey']); print('blockTime:', r['blockTime']); [print('memo:', i['parsed']) for i in m['instructions'] if i.get('program')=='spl-memo']"
```

Expected:

```
signer: 9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX
blockTime: 1788579612
memo: FACECHAIN/1 h=a8f1e58be5945cbddff36479a669b26fcb080d4dfb09623791a0a4fa946758c3 media=9d35a54d90cabb863eded7643b71be09a56ead8790ad13602b142d327527e3a5 cid=bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym sim=8777 url=https://www.instagram.com/p/Db6Jg25gffC
```

Three things to compare: `h=` equals the `bundle.json` digest from step 1, `media=` equals the `post_media.jpg` digest, and the signer is the registry wallet. The block time (2026-09-05 03:40:12 UTC) is when the commitment was made. The same transaction is visible in the explorer: https://explorer.solana.com/tx/2UZiq877N8gcJQWndUZinzmP6f19R8U1NXg18fDu6Zfg7WDm5D5bvzq2g7PuTk4tXwGGSYjrb1nDDwee1pqBdihw?cluster=devnet (open "Instructions", the memo text is shown in full).

You can also find the record from the hash alone, without the receipt: list the registry wallet's signatures and look for `h=<H>` in their memo fields.

```bash
curl -s https://api.devnet.solana.com -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":["9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX",{"limit":1000}]}' \
  | python3 -c "import json,sys; H='a8f1e58be5945cbddff36479a669b26fcb080d4dfb09623791a0a4fa946758c3'; [print(s['signature'], s['blockTime']) for s in json.load(sys.stdin)['result'] if s.get('memo') and 'h='+H in s['memo']]"
```

Expected: exactly one line, the signature above.

## 3. Check the attestation account

The Solana Attestation Service record lives at `v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N`. Confirm it exists and is owned by the attestation program, and that it contains H, the CID, the post URL and the similarity:

```bash
curl -s https://api.devnet.solana.com -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getAccountInfo","params":["v9Ui5T4wKzxMitn5vfs3Bnv1ZBeM7orkJWbTM8AF72N",{"encoding":"base64"}]}' \
  | python3 -c "
import json,sys,base64
v=json.load(sys.stdin)['result']['value']; raw=base64.b64decode(v['data'][0])
print('owner:', v['owner']); print('bytes:', len(raw))
for needle in (b'a8f1e58be5945cbddff36479a669b26fcb080d4dfb09623791a0a4fa946758c3', b'bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym', b'https://www.instagram.com/p/Db6Jg25gffC'):
    print(needle[:20].decode(), '->', 'present' if needle in raw else 'MISSING')
print('similarity_bps 8777 ->', 'present' if (8777).to_bytes(8,'little') in raw else 'MISSING')"
```

Expected: `owner: 22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG` and four `present` lines. (The account's data is Borsh-encoded: the hex hash, CID and URL are stored as length-prefixed UTF-8 strings and the similarity as a little-endian u64, so a byte search finds them.)

The address itself is not arbitrary: it is the program-derived address of `("attestation", credential Awhv5Djj…, schema DNnsTXgm…, nonce)` where the nonce is the 32 bytes of H. Anyone with `bundle.json` can recompute it; `facechain verify` does exactly that.

## 4. Fetch the same evidence from IPFS

```bash
curl -sL https://ipfs.io/ipfs/bafkreifi6hsyxzmuls65743epgtgtmtpzmea2tp3bfrdpenaut5jiz2yym -o /tmp/bundle.json
curl -sL https://ipfs.io/ipfs/bafkreie5gwsu3egkxodd5xwxmq5xdpqjuvxk3b4qvujwakyufuzhkj7duu -o /tmp/post_media.jpg
sha256sum /tmp/bundle.json /tmp/post_media.jpg
```

Expected: the same two digests as in step 1. Public gateways sometimes answer a first request with a plain-text timeout notice instead of the file (`head -c 100 /tmp/bundle.json` shows it); simply retry, or use `https://gateway.pinata.cloud/ipfs/<cid>` or `https://dweb.link/ipfs/<cid>`, which serve the same content.

## 5. Tamper test by hand

```bash
cp evidence/sample_run/post_media.jpg /tmp/tampered.jpg
python3 -c "p='/tmp/tampered.jpg'; d=bytearray(open(p,'rb').read()); d[len(d)//2]^=0xFF; open(p,'wb').write(d)"
sha256sum /tmp/tampered.jpg
```

Expected: any digest other than `9d35a54d…7527e3a5`, so the on-chain `media=` value no longer matches the file. The chain record cannot be edited to agree: its media hash was fixed at block time.

## 6. What this proves, and what it does not

Proved: at 2026-09-05 03:40:12 UTC the registry wallet committed to exactly these evidence bytes; the evidence names a specific public post and a similarity score; the same evidence is retrievable from IPFS; any change to the media or the bundle is detectable.

Not proved by the chain: that the similarity score is *correct*. That part is the face-recognition step, which you can re-run: the `candidates.json` next to the bundle lists all 40 candidates with their scores, and `facechain search --image evidence/sample_run/query.jpg` repeats the search (it needs a SerpApi key and costs two searches).
