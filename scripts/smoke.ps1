# Native Windows smoke test for facechain (PowerShell 5.1+).
#   scripts\smoke.ps1                       doctor + scan + live search (2 SerpApi searches)
#   scripts\smoke.ps1 -Chain                ... + run (memo) + verify + tamper test
#   scripts\smoke.ps1 -Chain -Sas           ... + SAS attestation (needs Node 22.6+ and `npm ci` in chain-ts)
# Requires: Python 3.12+ on PATH, the model pack in %USERPROFILE%\.insightface\models\buffalo_l,
# a devnet keypair at %USERPROFILE%\.config\solana\id.json, and .env with SERPAPI_KEY.
param(
    [string]$Image = "samples\ronaldo\subject.jpg",
    [switch]$Chain,
    [switch]$Sas
)

$env:PYTHONUTF8 = "1"                                   # emoji in post text must not crash the console
$env:SOLANA_KEYPAIR_PATH = Join-Path $env:USERPROFILE ".config\solana\id.json"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

$venv = Join-Path $env:USERPROFILE "venvs\facechain-win"
$fc = Join-Path $venv "Scripts\facechain.exe"
if (-not (Test-Path $fc)) {
    Write-Host "== creating venv $venv and installing facechain" -ForegroundColor Cyan
    python -m venv $venv
    & (Join-Path $venv "Scripts\python.exe") -m pip install -q -U pip
    & (Join-Path $venv "Scripts\python.exe") -m pip install -q "$repo"
}

function Step($name) { Write-Host "`n== $name" -ForegroundColor Cyan }

Step "doctor";  & $fc doctor --online
Step "scan";    & $fc scan --image $Image
Step "search";  & $fc search --image $Image --engines lens --json evidence\_windows.json
Write-Host "search exit code: $LASTEXITCODE (0 = ACCEPT, 2 = REVIEW)"

if ($Chain) {
    $sasFlag = @(); if ($Sas) { $sasFlag = @("--sas") }
    Step "run (cached search -> evidence -> devnet memo$(if ($Sas) { ' + attestation' }))"
    & $fc run --image $Image --engines lens @sasFlag
    $run = Get-ChildItem evidence -Directory |
        Where-Object { $_.Name -match '^\d{8}T\d{6}Z-' -and $_.Name -notmatch '_tampered$' } |
        Sort-Object Name -Descending | Select-Object -First 1
    Step "verify $($run.Name)";  & $fc verify --run $run.FullName
    Write-Host "verify exit code: $LASTEXITCODE (0 = VERIFIED)"
    Step "tamper";                & $fc verify --run $run.FullName --tamper
    Write-Host "tamper exit code: $LASTEXITCODE (1 = TAMPERED, as expected)"
}
Write-Host "`nSMOKE DONE" -ForegroundColor Green
