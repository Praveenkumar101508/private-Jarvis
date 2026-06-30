# IRA Portable — one-command start (Windows / PowerShell).
# Flow: check deps -> load demo.env -> verify master password -> start services ->
#       poll /health -> open browser on success. Every failure prints a clear reason.
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$EnvFile = if ($env:IRA_ENV_FILE) { $env:IRA_ENV_FILE } else { Join-Path $Here ".env" }
$ApiBase = if ($env:IRA_API_BASE) { $env:IRA_API_BASE } else { "http://127.0.0.1:8000" }
$FrontendUrl = if ($env:IRA_FRONTEND_URL) { $env:IRA_FRONTEND_URL } else { "http://localhost:3000" }
$ComposeFile = Join-Path $Root "docker-compose.portable.yml"
$ConfigDir = if ($env:IRA_CONFIG_DIR) { $env:IRA_CONFIG_DIR } else { Join-Path $Here "config" }
$ReadyTimeout = if ($env:IRA_READY_TIMEOUT) { $env:IRA_READY_TIMEOUT } else { "120" }

function Fail($msg) { Write-Error "ERROR: $msg"; exit 1 }
function Info($msg) { Write-Host ">> $msg" }

# 1. Dependencies
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python is required." }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "docker is required (Docker Desktop must be running)." }

# 2. Environment
if (-not (Test-Path $EnvFile)) { Fail "missing env file: $EnvFile (copy demo.env.example to .env and edit secrets)." }
Info "Loading $EnvFile"
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim()) }
}

# 3. Master password (refuses to continue without it)
Info "Verifying master password"
python (Join-Path $Here "verify_master_password.py") --config-dir $ConfigDir
if ($LASTEXITCODE -ne 0) { Fail "master password verification failed — not starting." }

# 4. Services
if (-not (Test-Path $ComposeFile)) { Fail "missing $ComposeFile (run from a complete IRA-Portable bundle)." }
Info "Starting core services (Postgres+pgvector, Redis, IRA API, frontend, local LLM)"
docker compose --env-file $EnvFile -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) { Fail "docker compose failed to start the stack." }

# 5. Health gate
Info "Waiting for IRA to become healthy ..."
python (Join-Path $Here "health_check.py") --base-url $ApiBase --timeout $ReadyTimeout
if ($LASTEXITCODE -eq 0) {
    Info "Opening $FrontendUrl"
    Start-Process $FrontendUrl
    Info "IRA is up."
} else {
    Fail "IRA did not become healthy. Check: docker compose -f `"$ComposeFile`" logs"
}
