# One-command setup for Windows (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = (Get-Command py -ErrorAction SilentlyContinue)
$python = if ($py) { "py" } else { "python" }
& $python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "Python 3.11+ is required: https://www.python.org/downloads/"; exit 1 }

Write-Host "-> Creating virtual environment (.venv)"
& $python -m venv .venv
$pda = ".\.venv\Scripts\pda.exe"
& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
Write-Host "-> Installing (about a minute)"
& .\.venv\Scripts\python.exe -m pip install -q -e .

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "-> Created .env (add your Telegram token later)" }

Write-Host "`n-> Quick demo with an example plan:`n"
& $pda demo --extra 0 | Select-Object -First 32
Write-Host "   ... (run 'pda demo' for the full tour)`n"

if (-not (Test-Path config\strategy.yaml)) {
    Write-Host "-> Now let's create YOUR plan:"
    & $pda init
}

& $pda doctor --offline

Write-Host @"

Done. Next:
  .\.venv\Scripts\Activate.ps1
  pda plan                      # this month's buy list with live prices
  pda import <positions.csv>    # optional: load what you already own
  # add TELEGRAM_BOT_TOKEN to .env, then:
  pda bot
"@
