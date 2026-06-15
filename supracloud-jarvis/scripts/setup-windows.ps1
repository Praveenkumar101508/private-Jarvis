<#
# ============================================================================
# L6 -- IRA one-time LOCAL setup for Windows (no Docker, Ollama 14B, private)
# ============================================================================
# Idempotent: safe to re-run. Does NOT touch the Linux scripts (setup.sh etc.),
# which stay for the future Docker/cloud path.
#
# What it does:
#   1. Checks prerequisites (Ollama, Python 3.11+, Node, PostgreSQL, Memurai)
#   2. Pulls the local chat model with Ollama
#   3. Creates the Postgres role + database and enables pgvector
#   4. Generates supracloud-jarvis/.env from .env.example with local values
#   5. Creates a Python venv + installs deps; installs frontend deps
#
# Usage (from the supracloud-jarvis/ folder):
#   powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
#   # optionally pass the Postgres superuser password:
#   ... -PgSuperPassword 'your_postgres_pw'
#
# NOTE: ASCII-only on purpose so it parses under Windows PowerShell 5.1.
# ============================================================================
#>
[CmdletBinding()]
param(
    # Password for the Postgres superuser ("postgres") used only to create the
    # app role/db. If omitted, you'll be prompted (or set $env:PGPASSWORD first).
    [string]$PgSuperPassword = $env:PGPASSWORD,
    [string]$PgSuperUser     = "postgres",
    [string]$OllamaModel     = "qwen3:14b",                  # L2: the local 14B chat model
    [string]$EmbeddingModel  = "BAAI/bge-large-en-v1.5",     # A7: sentence-transformers embedder (1024-dim)
    [string]$RerankerModel   = "BAAI/bge-reranker-v2-m3",    # A7: cross-encoder reranker
    [switch]$SkipDeps                                         # skip pip/npm install if set
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Resolve repo paths relative to this script (scripts/ lives under the project root)
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$EnvExample  = Join-Path $ProjectRoot ".env.example"
$EnvFile     = Join-Path $ProjectRoot ".env"
$FrontendDir = Join-Path $ProjectRoot "frontend"

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg"   -ForegroundColor Yellow }

function Test-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Portable hex secret (works on Windows PowerShell 5.1 -- no [Convert]::ToHexString)
function New-Secret([int]$bytes = 32) {
    $b = New-Object 'byte[]' $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return -join ($b | ForEach-Object { $_.ToString('x2') })
}

# -- 1. Prerequisite checks (install hints, non-fatal where possible) ---------
Write-Step "1. Checking prerequisites"

if (Test-Cmd ollama) { Write-Ok "Ollama found" }
else { Write-Warn "Ollama NOT found -- install from https://ollama.com/download/windows" }

if (Test-Cmd python) {
    $pyv = (python --version) 2>&1
    Write-Ok "Python found ($pyv) -- needs 3.11+"
} else { Write-Warn "Python NOT found -- install 3.11+ from https://www.python.org/downloads/" }

if (Test-Cmd node) { Write-Ok "Node found ($(node --version))" }
else { Write-Warn "Node NOT found -- install LTS from https://nodejs.org/" }

if (Test-Cmd psql) { Write-Ok "PostgreSQL client (psql) found" }
else { Write-Warn "psql NOT found -- install PostgreSQL 16 from https://www.postgresql.org/download/windows/ (with pgvector)" }

# L5: Memurai is a Redis-compatible Windows service (drop-in for localhost:6379)
$memurai = Get-Service -Name "Memurai*" -ErrorAction SilentlyContinue
if ($memurai) { Write-Ok "Memurai service found ($($memurai.Status))" }
else { Write-Warn "Memurai (Redis for Windows) NOT found -- install from https://www.memurai.com/get-memurai  (IRA needs Redis at localhost:6379)" }

# -- 2. Pull the Ollama model -------------------------------------------------
Write-Step "2. Pulling Ollama model: $OllamaModel"
if (Test-Cmd ollama) {
    ollama pull $OllamaModel
    Write-Ok "Model $OllamaModel ready"
} else {
    Write-Warn "Skipping pull -- Ollama not installed. After installing run: ollama pull $OllamaModel"
}
# NOTE: embeddings stay on local sentence-transformers (BGE, 1024-dim) per L3 --
# no Ollama embedding model is pulled (that would change vector dims + break DB).

# -- 3. Create DB role + database + pgvector ----------------------------------
Write-Step "3. Setting up PostgreSQL (role 'jarvis', db 'jarvis_db', pgvector)"
if (Test-Cmd psql) {
    if (-not $PgSuperPassword) {
        $sec = Read-Host "Enter password for Postgres superuser '$PgSuperUser'" -AsSecureString
        $PgSuperPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    $env:PGPASSWORD = $PgSuperPassword
    $appPw = New-Secret 18   # generated app DB password, written into .env below

    # Idempotent role + database creation (CREATE DATABASE has no IF NOT EXISTS)
    $sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jarvis') THEN
    CREATE ROLE jarvis LOGIN PASSWORD '$appPw';
  ELSE
    ALTER ROLE jarvis WITH LOGIN PASSWORD '$appPw';
  END IF;
END `$`$;
SELECT 'CREATE DATABASE jarvis_db OWNER jarvis'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'jarvis_db')\gexec
"@
    $sql | psql -h localhost -U $PgSuperUser -d postgres -v ON_ERROR_STOP=1 -f -
    psql -h localhost -U $PgSuperUser -d jarvis_db -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
    Write-Ok "Database ready with pgvector. App DB password generated and saved to .env."
    $script:GeneratedDbPassword = $appPw
} else {
    Write-Warn "Skipping DB setup -- psql not installed. After installing PostgreSQL + pgvector, run:"
    Write-Warn "  psql -U postgres -c `"CREATE ROLE jarvis LOGIN PASSWORD 'CHANGE_ME';`""
    Write-Warn "  psql -U postgres -c `"CREATE DATABASE jarvis_db OWNER jarvis;`""
    Write-Warn "  psql -U postgres -d jarvis_db -c `"CREATE EXTENSION IF NOT EXISTS vector;`""
    $script:GeneratedDbPassword = "CHANGE_ME"
}

# -- 4. Generate .env from .env.example with local values ---------------------
Write-Step "4. Generating .env (local / Ollama / no-Docker)"
if (Test-Path $EnvFile) {
    Write-Warn ".env already exists -- leaving it untouched. Delete it and re-run to regenerate."
} else {
    if (-not (Test-Path $EnvExample)) { throw ".env.example not found at $EnvExample" }
    $content = Get-Content $EnvExample -Raw

    # Fill required (no-default) secrets and force local-mode values.
    $repl = [ordered]@{
        "POSTGRES_PASSWORD"  = $script:GeneratedDbPassword
        "REDIS_PASSWORD"     = ""                # Memurai default: no auth
        "VLLM_API_KEY"       = "ollama"          # dummy -- unused when LLM_BACKEND=ollama
        "IRA_SECRET_KEY"     = (New-Secret 32)
        "IRA_ADMIN_PASSWORD" = (New-Secret 12)
    }
    foreach ($k in $repl.Keys) {
        $line = "$k=$($repl[$k])"
        if ($content -match "(?m)^$k=.*$") { $content = $content -replace "(?m)^$k=.*$", $line }
        else { $content += "`n$line" }
    }

    # Append the L2/L4/L5 local-mode block (keys the example may not list).
    $localBlock = @"

# -- L6: local (no-Docker) overrides -- Shadow PC, Ollama 14B, private --
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL_FAST=$OllamaModel
OLLAMA_MODEL_DEEP=$OllamaModel
OLLAMA_MODEL_REASONING=$OllamaModel
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
REDIS_HOST=localhost
REDIS_PORT=6379
DEV_MODE=false
IRA_DOMAIN=localhost
# A7: accuracy levers OFF for the FIRST boot test (clean L1-L9 baseline, no new
# variables). The models are still pre-downloaded below, so flipping these to
# true after the boot test passes is instant. See ACCURACY_LAYER.md.
RERANKER_ENABLED=false
WEB_SEARCH_ENABLED=false
# Voice is OFF by default locally. If you enable voice, mint a real JWT and set:
# IRA_VOICE_API_TOKEN=<signed-jwt>   (see LOCAL_SETUP.md)
"@
    ($content.TrimEnd() + "`n" + $localBlock + "`n") | Set-Content -Path $EnvFile -Encoding utf8
    Write-Ok ".env written with generated secrets and LLM_BACKEND=ollama"
    Write-Warn "Admin password was randomly generated -- see IRA_ADMIN_PASSWORD in .env to log in."
}

# -- 5. Python + frontend dependencies ----------------------------------------
if (-not $SkipDeps) {
    Write-Step "5. Installing Python dependencies (venv)"
    if (Test-Cmd python) {
        $venv = Join-Path $ProjectRoot ".venv"
        if (-not (Test-Path $venv)) { python -m venv $venv }
        $pip = Join-Path $venv "Scripts\pip.exe"
        & $pip install --upgrade pip
        & $pip install -r (Join-Path $ProjectRoot "ira\requirements.txt")
        Write-Ok "Python deps installed into .venv"

        # A7: pre-download the CPU models so the first chat doesn't stall on a
        # surprise download. Embedder is always used; reranker is pre-cached even
        # though it's OFF for the first boot, so enabling it later is instant.
        Write-Step "5b. Pre-downloading embedding + reranker models (CPU, one-time)"
        $py = Join-Path $venv "Scripts\python.exe"
        $dl = "from sentence_transformers import SentenceTransformer, CrossEncoder; " +
              "print('embedder...'); SentenceTransformer('$EmbeddingModel'); " +
              "print('reranker...'); CrossEncoder('$RerankerModel'); print('models cached')"
        try {
            & $py -c $dl
            Write-Ok "Embedder ($EmbeddingModel) and reranker ($RerankerModel) cached"
        } catch {
            Write-Warn "Model pre-download failed (will download on first use instead): $_"
        }
    } else { Write-Warn "Skipping pip -- Python not installed." }

    Write-Step "5c. Installing frontend dependencies"
    if ((Test-Cmd npm) -and (Test-Path $FrontendDir)) {
        Push-Location $FrontendDir
        npm install
        Pop-Location
        Write-Ok "Frontend deps installed"
    } else { Write-Warn "Skipping npm install -- npm or frontend/ missing." }
} else {
    Write-Warn "Skipping dependency install (-SkipDeps)."
}

# -- Next steps ---------------------------------------------------------------
Write-Step "Setup complete -- next steps"
Write-Host @"
  1. Make sure these are running:
       - Ollama          (tray app or 'ollama serve')
       - PostgreSQL 16    (Windows service)
       - Memurai          (Redis-compatible Windows service, localhost:6379)
  2. Start everything:
       powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
  3. Open the app:  http://localhost:3000   (API at http://localhost:8000)

  Your admin login is in .env (IRA_ADMIN_USERNAME / IRA_ADMIN_PASSWORD).
"@ -ForegroundColor White
