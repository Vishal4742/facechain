# VHS tape: records the real pipeline end to end into an MP4 (no editing; every command runs live).
#   vhs scripts/demo.tape            -> demo/facechain-demo.mp4
# Requires: vhs, ttyd, ffmpeg on PATH; .env with SERPAPI_KEY (+ PINATA_JWT, SAS_* optional).

Output demo/facechain-demo.mp4

Set Shell "bash"
Set FontSize 17
Set FontFamily "DejaVu Sans Mono"
Set Width 1600
Set Height 900
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set WindowBar Colorful
Set WindowBarSize 36

Hide
Type "source ~/.venvs/facechain/bin/activate && cd /mnt/d/HHGOA/facechain && export PS1='\[\e[1;35m\]facechain\[\e[0m\] $ ' && clear"
Enter
Sleep 1s
Show

Type "# HH Goa 2026 - Task 3: face scan -> genuine social search -> Solana devnet record -> verify"
Enter
Sleep 2s

Type "facechain scan --image samples/ronaldo/subject.jpg"
Enter
Wait+Screen@60s /face\(s\) in/
Sleep 3s

Type "facechain run --image samples/ronaldo/subject.jpg --live --engines lens,identity --sas"
Enter
Wait+Screen@240s /(explorer: .*\n.*explorer:|search failed|not accepted)/
Sleep 6s

Type "RUN=$(ls -td evidence/2* | grep -v _tampered | head -1); echo $RUN"
Enter
Sleep 1s
Type "sha256sum $RUN/bundle.json   # must equal h= in the on-chain memo"
Enter
Sleep 4s

Type "solana confirm -v $(python -c \"import json;print(json.load(open('$RUN/receipt.json'))['signature'])\") -u devnet | grep -E 'Program log: Memo|Status|Block Time' | cut -c1-150"
Enter
Wait+Screen@60s /Memo|Status/
Sleep 5s

Type "facechain verify --run $RUN"
Enter
Wait+Screen@120s /VERIFIED|TAMPERED|UNANCHORED/
Sleep 6s

Type "facechain verify --run $RUN --tamper"
Enter
Wait+Screen@120s /TAMPERED|VERIFIED/
Sleep 6s

Type "cat $RUN/receipt.json | python -c \"import json,sys; r=json.load(sys.stdin); print('explorer:', r['explorer']); print('attestation:', r['sas']['attestation']); print('bundle CID:', r['bundle_cid'])\""
Enter
Sleep 6s
