# VHS tape: records the real pipeline end to end into an MP4 (no editing; every command runs live).
#   vhs scripts/demo.tape            -> demo/facechain-demo.mp4
# Requires: vhs, ttyd, ffmpeg on PATH; .env with SERPAPI_KEY (+ PINATA_JWT, SAS_* optional).

Output demo/facechain-demo.mp4

Set Shell "bash"
Set FontSize 16
Set FontFamily "DejaVu Sans Mono"
Set Width 1440
Set Height 840
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set WindowBar Colorful
Set WindowBarSize 34

Hide
Type "cd /mnt/d/HHGOA/facechain && source ~/.venvs/facechain/bin/activate && source scripts/demo_helpers.sh && export PYTHONWARNINGS=ignore PS1='facechain > ' && clear"
Enter
Sleep 1s
Show

Type "# HH Goa 2026 - Task 3: face scan -> genuine social search -> Solana devnet record -> verify"
Enter
Sleep 2s

Type "facechain scan --image samples/ronaldo/subject.jpg"
Enter
Wait@90s /facechain >\s*$/
Sleep 3s

Type "facechain run --image samples/ronaldo/subject.jpg --live --engines lens,identity --sas"
Enter
Wait@400s /facechain >\s*$/
Sleep 6s

Type "RUN=$(demo_run_dir); echo $RUN"
Enter
Wait@10s /facechain >\s*$/
Sleep 1s
Type "sha256sum $RUN/bundle.json   # must equal h= in the on-chain memo"
Enter
Wait@10s /facechain >\s*$/
Sleep 4s

Type "demo_memo_log $RUN   # read the memo back from the transaction logs (solana CLI)"
Enter
Wait@120s /facechain >\s*$/
Sleep 5s

Type "facechain verify --run $RUN"
Enter
Wait@180s /facechain >\s*$/
Sleep 6s

Type "facechain verify --run $RUN --tamper"
Enter
Wait@180s /facechain >\s*$/
Sleep 6s

Type "demo_links $RUN"
Enter
Wait@10s /facechain >\s*$/
Sleep 7s
