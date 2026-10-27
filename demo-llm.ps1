# LoopSmith demo: model-backed A/B evaluation on the scenario pack.
# Requires an OpenAI-compatible endpoint in the environment:
#   LOOPSMITH_LLM_BASE_URL  (default https://openrouter.ai/api/v1)
#   LOOPSMITH_LLM_API_KEY
#   LOOPSMITH_LLM_MODEL     (suggested: cohere/north-mini-code:free)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$env:LOOPSMITH_DB = Join-Path $PWD ".loopsmith\loopsmith.db"
$env:LOOPSMITH_EXPORT_DIR = Join-Path $PWD "dist"

# Model settings come from .env (auto-loaded by LoopSmith) or the shell.
python -c "import sys; from loopsmith.config import load_llm_config; sys.exit(0 if load_llm_config().configured else 1)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "No model endpoint configured. Put this in .env (KEY=VALUE):" -ForegroundColor Yellow
  Write-Host '  LOOPSMITH_LLM_BASE_URL=https://openrouter.ai/api/v1'
  Write-Host '  LOOPSMITH_LLM_MODEL=cohere/north-mini-code:free'
  Write-Host '  LOOPSMITH_LLM_API_KEY=sk-or-...'
  Write-Host "or set the three LOOPSMITH_LLM_* environment variables." -ForegroundColor Yellow
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

Write-Host "`n== behavioral A/B for the instruction proposal ==" -ForegroundColor Cyan
Write-Host "1 scenario x 2 arms x 1 run (~8-16 requests). Add --scenario for more" -ForegroundColor DarkGray
Write-Host "fixtures, or drop --scenario to run the whole pack (~30-48 requests)." -ForegroundColor DarkGray
lsm eval $instruction.id --runs 1 --scenario acme-auth-fix

Write-Host "`n== transcript sample ==" -ForegroundColor Cyan
$latest = Get-ChildItem ".loopsmith\runs" -Filter *.json -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime | Select-Object -First 1
if ($latest) { Get-Content $latest.FullName -TotalCount 40 }

Write-Host "`nIf the verdict is promote: lsm approve $($instruction.id)" -ForegroundColor Yellow
Write-Host "Then: lsm export" -ForegroundColor Yellow