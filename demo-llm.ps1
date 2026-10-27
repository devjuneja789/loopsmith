# LoopSmith model-backed demo (P1): A/B evaluation on the scenario pack.
# Requires an OpenAI-compatible endpoint in the environment:
#   LOOPSMITH_LLM_BASE_URL  (default https://openrouter.ai/api/v1)
#   LOOPSMITH_LLM_API_KEY
#   LOOPSMITH_LLM_MODEL     (suggested: cohere/north-mini-code:free)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$env:LOOPSMITH_DB = Join-Path $PWD ".loopsmith\loopsmith.db"
$env:LOOPSMITH_EXPORT_DIR = Join-Path $PWD "dist"

if (-not $env:LOOPSMITH_LLM_API_KEY) {
  Write-Host "Set the model endpoint first, e.g.:" -ForegroundColor Yellow
  Write-Host '  $env:LOOPSMITH_LLM_BASE_URL="https://openrouter.ai/api/v1"'
  Write-Host '  $env:LOOPSMITH_LLM_MODEL="cohere/north-mini-code:free"'
  Write-Host '  $env:LOOPSMITH_LLM_API_KEY="sk-or-..."'
  exit 1
}

function lsm { python -m loopsmith.app @args }

Write-Host "`n== setup ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force .loopsmith, dist -ErrorAction SilentlyContinue
lsm init
lsm import examples/traces/acme-api-session1.jsonl --project acme-api
lsm import examples/traces/acme-api-session2.jsonl --project acme-api
lsm mine

$json = lsm proposals list --format json | ConvertFrom-Json
$instruction = $json | Where-Object { $_.kind -eq "instruction" } | Select-Object -First 1

Write-Host "`n== benchmark pack ==" -ForegroundColor Cyan
lsm benchmark list

Write-Host "`n== behavioral A/B for the instruction proposal (N=1) ==" -ForegroundColor Cyan
Write-Host "3 scenarios x 2 arms x 1 run; ~10-25 requests." -ForegroundColor DarkGray
lsm eval $instruction.id --runs 1

Write-Host "`n== transcript sample ==" -ForegroundColor Cyan
$latest = Get-ChildItem ".loopsmith\runs" -Filter *.json -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime | Select-Object -First 1
if ($latest) { Get-Content $latest.FullName -TotalCount 40 }

Write-Host "`nIf the verdict is promote: lsm approve $($instruction.id)" -ForegroundColor Yellow
Write-Host "Then: lsm export" -ForegroundColor Yellow