<#
.SYNOPSIS
  Bring up the full IRA native stack on Windows (Shadow PC) in dependency order,
  checking each service is healthy. Replaces docker-compose / `make up` (there is
  no docker-compose.yml; the stack runs native on Windows per CLAUDE.md).

.DESCRIPTION
  Order: Postgres -> Memurai (Redis) -> Ollama -> Hermes gateway (:8642)
         -> web-research backends (SearXNG / Crawl4AI) -> IRA backend (uvicorn)
         -> IRA frontend (Next).
  Each service is started only if it isn't already up, then probed until healthy.
  SearXNG / Crawl4AI are optional (web research fails soft) — a miss is WARN, not
  fatal. Prints a per-service status line and a final "ALL UP" or the first failure.

.USAGE
  pwsh -File .\start-ira.ps1                 # bring everything up
  pwsh -File .\start-ira.ps1 -SkipFrontend   # backend only
  Loads .env from this folder if present.
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [int]$ReadyTimeoutSec = 90
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$iraDir = Join-Path $root "ira"
$frontendDir = Join-Path $root "frontend"

# ── .env loader ───────────────────────────────────────────────────────────────
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $name = $matches[1].Trim(); $val = $matches[2].Trim().Trim('"')
            [Environment]::SetEnvironmentVariable($name, $val, "Process")
        }
    }
    Write-Host "Loaded .env" -ForegroundColor DarkGray
}

function Get-EnvOr([string]$name, [string]$default) {
    $v = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($v)) { return $default } else { return $v }
}

# ── probes ────────────────────────────────────────────────────────────────────
function Test-Tcp([string]$h, [int]$port) {
    try { (Test-NetConnection -ComputerName $h -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded }
    catch { $false }
}

function Test-Http([string]$url, [hashtable]$headers = @{}) {
    try {
        $r = Invoke-WebRequest -Uri $url -Headers $headers -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -lt 500
    } catch { return $false }
}

function Wait-Until([scriptblock]$check, [int]$timeoutSec) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (& $check) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

$results = [ordered]@{}
function Set-Status([string]$name, [string]$state, [string]$detail = "") {
    $results[$name] = @{ state = $state; detail = $detail }
    $color = switch ($state) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("  [{0,-4}] {1,-12} {2}" -f $state, $name, $detail) -ForegroundColor $color
}

Write-Host "Starting IRA native stack..." -ForegroundColor Cyan

# ── 1. Postgres (native service) ──────────────────────────────────────────────
$pgPort = [int](Get-EnvOr "POSTGRES_PORT" "5432")
if (-not (Test-Tcp "localhost" $pgPort)) {
    Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Start-Service -ErrorAction SilentlyContinue
}
if (Wait-Until { Test-Tcp "localhost" $pgPort } $ReadyTimeoutSec) { Set-Status "postgres" "OK" "port $pgPort" }
else { Set-Status "postgres" "FAIL" "not reachable on $pgPort" }

# ── 2. Memurai (Redis for Windows) ────────────────────────────────────────────
$redisPort = [int](Get-EnvOr "REDIS_PORT" "6379")
if (-not (Test-Tcp "localhost" $redisPort)) {
    Get-Service -Name "Memurai" -ErrorAction SilentlyContinue | Start-Service -ErrorAction SilentlyContinue
}
if (Wait-Until { Test-Tcp "localhost" $redisPort } $ReadyTimeoutSec) { Set-Status "redis" "OK" "port $redisPort (Memurai)" }
else { Set-Status "redis" "FAIL" "not reachable on $redisPort" }

# ── 3. Ollama (serve, then ensure the fast/deep models are pulled and warm) ─────
$ollamaBase = (Get-EnvOr "OLLAMA_BASE_URL" "http://localhost:11434/v1") -replace "/v1$",""
$keepAlive  = Get-EnvOr "OLLAMA_KEEP_ALIVE" "30m"
$fastModel  = Get-EnvOr "OLLAMA_MODEL_FAST" "qwen3:8b"     # voice / low-latency tier
$deepModel  = Get-EnvOr "OLLAMA_MODEL_DEEP" "qwen3:14b"    # deep / reasoning tier
if (-not (Test-Http "$ollamaBase/api/tags")) {
    # KV-cache quant + flash attention so qwen3:8b and qwen3:14b both fit warm on the
    # 20GB A4500; keep_alive keeps them resident between turns (faster TTFT).
    [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", $keepAlive, "Process")
    if (-not (Get-EnvOr "OLLAMA_FLASH_ATTENTION" "")) { [Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "Process") }
    if (-not (Get-EnvOr "OLLAMA_KV_CACHE_TYPE" "")) { [Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "Process") }
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
}
if (Wait-Until { Test-Http "$ollamaBase/api/tags" } $ReadyTimeoutSec) {
    # Pull each model if missing, then warm it (load into VRAM, pinned by keep_alive).
    $tags = ""
    try { $tags = (& ollama list 2>$null | Out-String) } catch {}
    foreach ($m in @($fastModel, $deepModel)) {
        if ($tags -notmatch [regex]::Escape($m)) {
            Write-Host "  ollama pull $m ..." -ForegroundColor DarkGray
            & ollama pull $m 2>$null
        }
        try {
            $body = @{ model = $m; prompt = "ok"; stream = $false; keep_alive = $keepAlive } | ConvertTo-Json
            Invoke-RestMethod -Method Post -Uri "$ollamaBase/api/generate" -Body $body -ContentType "application/json" -TimeoutSec 120 | Out-Null
        } catch {}
    }
    Set-Status "ollama" "OK" "$ollamaBase ($fastModel + $deepModel warm, keep_alive=$keepAlive)"
}
else { Set-Status "ollama" "FAIL" "no response at $ollamaBase" }

# ── 4. Hermes gateway (:8642) ─────────────────────────────────────────────────
$useHermes = (Get-EnvOr "IRA_USE_HERMES" "false").ToLower()
$hermesUrl = (Get-EnvOr "IRA_HERMES_URL" "http://127.0.0.1:8642/v1").TrimEnd("/")
$hermesKey = Get-EnvOr "IRA_HERMES_KEY" ""
$hermesHeaders = @{}
if ($hermesKey) { $hermesHeaders = @{ Authorization = "Bearer $hermesKey" } }
if ($useHermes -in @("1","true","yes","on")) {
    if (-not (Test-Http "$hermesUrl/models" $hermesHeaders)) {
        $launcher = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\ira-hermes-gateway.vbs"
        if (Test-Path $launcher) { Start-Process "wscript.exe" -ArgumentList "`"$launcher`"" -ErrorAction SilentlyContinue }
        else { Start-Process -FilePath "hermes" -ArgumentList "gateway" -WindowStyle Hidden -ErrorAction SilentlyContinue }
    }
    if (Wait-Until { Test-Http "$hermesUrl/models" $hermesHeaders } $ReadyTimeoutSec) { Set-Status "hermes" "OK" $hermesUrl }
    else { Set-Status "hermes" "FAIL" "no response at $hermesUrl" }
} else {
    Set-Status "hermes" "WARN" "IRA_USE_HERMES not enabled (legacy engine)"
}

# ── 5. Web-research backends (optional — research fails soft) ──────────────────
$searxng = (Get-EnvOr "SEARXNG_URL" "http://localhost:8888").TrimEnd("/")
if (Test-Http "$searxng/" ) { Set-Status "searxng" "OK" $searxng }
else { Set-Status "searxng" "WARN" "down ($searxng) — web search disabled, research fails soft" }

$crawl4ai = (Get-EnvOr "CRAWL4AI_URL" "http://localhost:11235").TrimEnd("/")
if (Test-Http "$crawl4ai/health") { Set-Status "crawl4ai" "OK" $crawl4ai }
else { Set-Status "crawl4ai" "WARN" "down ($crawl4ai) — web reader disabled, research fails soft" }

# ── 6. IRA backend (uvicorn) ──────────────────────────────────────────────────
$apiPort = [int](Get-EnvOr "IRA_API_PORT" "8000")
if (-not (Test-Http "http://127.0.0.1:$apiPort/health")) {
    Start-Process -FilePath "python" `
        -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","$apiPort" `
        -WorkingDirectory $iraDir -WindowStyle Hidden -ErrorAction SilentlyContinue
}
if (Wait-Until { Test-Http "http://127.0.0.1:$apiPort/health" } $ReadyTimeoutSec) { Set-Status "ira-api" "OK" "http://127.0.0.1:$apiPort" }
else { Set-Status "ira-api" "FAIL" "no /health on $apiPort" }

# ── 7. IRA frontend (Next) ────────────────────────────────────────────────────
if (-not $SkipFrontend) {
    $fePort = [int](Get-EnvOr "FRONTEND_PORT" "3000")
    if (-not (Test-Tcp "localhost" $fePort)) {
        Start-Process -FilePath "npm" -ArgumentList "run","start" `
            -WorkingDirectory $frontendDir -WindowStyle Hidden -ErrorAction SilentlyContinue
    }
    if (Wait-Until { Test-Tcp "localhost" $fePort } $ReadyTimeoutSec) { Set-Status "frontend" "OK" "http://localhost:$fePort" }
    else { Set-Status "frontend" "FAIL" "not reachable on $fePort" }
} else {
    Set-Status "frontend" "WARN" "skipped (-SkipFrontend)"
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
$failed = $results.GetEnumerator() | Where-Object { $_.Value.state -eq "FAIL" }
if ($failed) {
    Write-Host ("STACK NOT FULLY UP — failed: " + ($failed.Name -join ", ")) -ForegroundColor Red
    exit 1
} else {
    Write-Host "ALL UP. IRA is online. Good morning." -ForegroundColor Green
    exit 0
}
