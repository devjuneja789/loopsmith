# LoopSmith demo -- the model-free pipeline.
# Run from the repo root: powershell -ExecutionPolicy Bypass -File demo.ps1
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# self-contained and model-free: ignore any .env and shell model settings
$env:LOOPSMITH_SKIP_DOTENV = "1"
$env:LOOPSMITH_DB = Join-Path $PWD ".loopsmith\loopsmith.db"
$env:LOOPSMITH_EXPORT_DIR = Join-Path $PWD "dist"
Remove-Item Env:\LOOPSMITH_LLM_API_KEY -ErrorAction SilentlyContinue

function lsm { python -m loopsmith.app @args }

Write-Host "`n== 0. clean slate ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force .loopsmith, dist -ErrorAction SilentlyContinue
lsm init

Write-Host "`n== 1. import two coding-session traces ==" -ForegroundColor Cyan
lsm import examples/traces/acme-api-session1.jsonl --project acme-api
lsm import examples/traces/acme-api-session2.jsonl --project acme-api

Write-Host "`n== 2. mine evidence-cited refinement proposals ==" -ForegroundColor Cyan
lsm mine
lsm proposals list

$json = lsm proposals list --format json | ConvertFrom-Json
$instruction = $json | Where-Object { $_.kind -eq "instruction" } | Select-Object -First 1

Write-Host "`n== 3. inspect the strongest proposal (evidence-grounded) ==" -ForegroundColor Cyan
lsm proposals show $instruction.id

Write-Host "`n== 4. eval: static gates decide what may proceed ==" -ForegroundColor Cyan
foreach ($p in $json) { lsm eval $p.id }

Write-Host "`n== 5. human approval gate (no model configured -> --force required) ==" -ForegroundColor Cyan
Write-Host "without --force this is refused (exit 1):" -ForegroundColor Yellow
$ErrorActionPreference = "Continue"
lsm approve $json[0].id --yes 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
foreach ($p in $json) { lsm approve $p.id --yes --force }

Write-Host "`n== 6. export the approved harness as Markdown ==" -ForegroundColor Cyan
lsm export
Get-Content dist/AGENTS.md

Write-Host "`n== 7. continual loop: new evidence arrives -> versioned update ==" -ForegroundColor Cyan
lsm import examples/traces/acme-api-session3.jsonl --project acme-api
lsm mine
$pending = @(lsm proposals list --status pending --format ids)[0]
lsm proposals diff $pending
lsm eval $pending
lsm approve $pending --yes --force
lsm history instruction use-python-runtests-py

Write-Host "`n== 8. rollback: the gate is reversible ==" -ForegroundColor Cyan
lsm rollback instruction use-python-runtests-py
lsm history instruction use-python-runtests-py
lsm export --format agents
Get-Content dist/AGENTS.md

Write-Host "`nDone. DB: .loopsmith/loopsmith.db  Exports: dist/" -ForegroundColor Green