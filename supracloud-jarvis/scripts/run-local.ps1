<#
# ============================================================================
# L6 -- IRA local dev launcher for Windows (no Docker)
# ============================================================================
# Starts the API, (optional) worker, and frontend -- each in its own window --
# after sanity-checking Ollama / Postgres / Memurai. Does NOT touch the Linux
# scripts (dev-start.sh etc.), which stay for the future Docker/cloud path.
#
# Usage (from the supracloud-jarvis/ folder):
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
#   ... -NoWorker      # don't start the background worker
#   ... -NoFrontend    # API only
#
# NOTE: ASCII-only on purpose so it parses under Windows PowerShell 5.1.
# ============================================================================
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [switch]$NoWorker,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$IraDir      = Join-Path $ProjectRoot "ira"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$Venv        = Join-Path $ProjectRoot ".venv"

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg"   -ForegroundColor Yellow }
function Test-Cmd($name)  { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Prefer the venv's python if setup-windows.ps1 created one
$Python = if (Test-Path (Join-Path $Venv "Scripts\python.exe")) { Join-Path $Venv "Scripts\python.exe" } else { "python" }

# -- Pre-flight checks --------------------------------------------------------
Write-Step "Pre-flight"

# Ollama: make sure the daemon answers on 11434
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
    Write-Ok "Ollama responding on :11434"
} catch {
    Write-Warn "Ollama not responding on :11434 -- starting 'ollama serve' in a new window."
    if (Test-Cmd ollama) { Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized }
    else { Write-Warn "Ollama not installed -- run setup-windows.ps1 first." }
}

# Postgres
if (Test-Cmd pg_isready) {
    pg_isready -h localhost -p 5432 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "Postgres accepting connections on :5432" }
    else { Write-Warn "Postgres not ready on :5432 -- start the PostgreSQL service." }
} else { Write-Warn "pg_isready not found -- ensure PostgreSQL is running on :5432." }

# Memurai / Redis
$memurai = Get-Service -Name "Memurai*" -ErrorAction SilentlyContinue
if ($memurai) {
    if ($memurai.Status -ne "Running") { Write-Warn "Memurai is $($memurai.Status) -- starting it."; Start-Service $memurai.Name }
    Write-Ok "Memurai (Redis) running on :6379"
} else { Write-Warn "Memurai service not found -- IRA needs Redis at localhost:6379 (run setup-windows.ps1)." }

# -- Start the API (uvicorn main:app) -----------------------------------------
# Run from ira/ so the app's bare imports (from config import ...) resolve.
Write-Step "Starting API on http://localhost:$ApiPort"
$apiCmd = "Set-Location '$IraDir'; & '$Python' -m uvicorn main:app --host 0.0.0.0 --port $ApiPort --reload"
Start-Process -FilePath "powershell" -ArgumentList "-NoExit","-Command",$apiCmd
Write-Ok "API window launched (uvicorn main:app)"

# -- Start the worker (apscheduler) -------------------------------------------
if (-not $NoWorker) {
    Write-Step "Starting background worker"
    $workerCmd = "Set-Location '$IraDir'; & '$Python' -m worker.main"
    Start-Process -FilePath "powershell" -ArgumentList "-NoExit","-Command",$workerCmd
    Write-Ok "Worker window launched (python -m worker.main)"
} else { Write-Warn "Worker skipped (-NoWorker)." }

# -- Start the frontend (next dev) --------------------------------------------
if (-not $NoFrontend) {
    Write-Step "Starting frontend on http://localhost:3000"
    if (Test-Path $FrontendDir) {
        $feCmd = "Set-Location '$FrontendDir'; npm run dev"
        Start-Process -FilePath "powershell" -ArgumentList "-NoExit","-Command",$feCmd
        Write-Ok "Frontend window launched (npm run dev)"
    } else { Write-Warn "frontend/ not found -- skipping." }
} else { Write-Warn "Frontend skipped (-NoFrontend)." }

Write-Step "IRA is starting"
Write-Host @"
  Frontend : http://localhost:3000
  API      : http://localhost:$ApiPort   (docs at /docs)
  Engine   : Ollama (local, no Docker)

  Each service runs in its own PowerShell window -- close a window to stop it.
"@ -ForegroundColor White
