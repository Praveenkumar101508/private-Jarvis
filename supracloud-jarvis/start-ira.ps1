<#
.SYNOPSIS
  Bring up the full IRA native stack on Windows (Shadow PC) in dependency order,
  checking each service is healthy. Replaces docker-compose / `make up` (there is
  no docker-compose.yml; the stack runs native on Windows per CLAUDE.md).

.DESCRIPTION
  Order: Postgres -> Memurai (Redis) -> Ollama (pull + warm fast/deep) -> Hermes
         (hermes -z one-shot check) -> Supertonic TTS warm -> web-research
         (SearXNG / Crawl4AI) -> IRA backend (uvicorn) -> IRA frontend (Next).
  Each service is started only if it isn't already up, then probed until healthy.
  SearXNG / Crawl4AI and Supertonic are optional (fail soft) — a miss is WARN, not
  fatal. Prints a per-service status line and a final "ALL UP" or the first failure.

.USAGE
  pwsh -File .\start-ira.ps1                   # bring everything up
  pwsh -File .\start-ira.ps1 -SkipFrontend     # backend only
  pwsh -File .\start-ira.ps1 -InstallAutostart # also drop a login autostart launcher
  Loads .env from this folder if present.
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$InstallAutostart,
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

# Resolve the hermes executable the same way ira/hermes_bridge.py does:
# IRA_HERMES_BIN -> PATH -> the known native install. Returns $null if absent.
function Resolve-HermesBin {
    $envBin = [Environment]::GetEnvironmentVariable("IRA_HERMES_BIN", "Process")
    if ($envBin -and (Test-Path $envBin)) { return $envBin }
    $cmd = Get-Command "hermes" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = $env:LOCALAPPDATA
    if ($local) {
        $cand = Join-Path $local "hermes\hermes-agent\venv\Scripts\hermes.exe"
        if (Test-Path $cand) { return $cand }
    }
    return $null
}

# Smoke-test the `hermes -z` subprocess seam (the bridge's actual call path —
# Hermes 0.15.2 has no HTTP gateway). Bounded by $timeoutSec; OK = exit 0 + output.
function Test-HermesOneShot([string]$bin, [int]$timeoutSec) {
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $bin `
            -ArgumentList "--accept-hooks","-z","Reply with the single word: ready" `
            -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        if (-not $p.WaitForExit($timeoutSec * 1000)) { try { $p.Kill() } catch {}; return $false }
        $text = Get-Content $out -Raw -ErrorAction SilentlyContinue
        return ($p.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($text))
    } catch { return $false }
    finally { Remove-Item $out, $err -ErrorAction SilentlyContinue }
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

# ── Optional: install a login autostart launcher (no admin needed) ──────────────
# Mirrors the Hermes VBS trick: a hidden .vbs in the Startup folder runs this very
# script at logon, so the whole stack comes up without anyone touching a terminal.
if ($InstallAutostart) {
    $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    $vbsPath = Join-Path $startupDir "ira-stack.vbs"
    $self = $PSCommandPath
    $vbs = @"
' Auto-generated by start-ira.ps1 -InstallAutostart — boots the IRA stack hidden at logon.
Set sh = CreateObject("WScript.Shell")
sh.Run "pwsh -NoProfile -ExecutionPolicy Bypass -File ""$self""", 0, False
"@
    Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII
    Write-Host "Installed login autostart: $vbsPath" -ForegroundColor Green
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

# ── 4. Hermes engine (hermes -z one-shot — 0.15.2 ships NO :8642 HTTP gateway) ──
# The bridge reaches Hermes via `hermes -z`, not an HTTP port (CLAUDE.md verified
# 0.15.2 has no key-gated OpenAI gateway). So we smoke-test that subprocess seam.
$useHermes = (Get-EnvOr "IRA_USE_HERMES" "false").ToLower()
$hermesBin = Resolve-HermesBin
if ($useHermes -in @("1","true","yes","on")) {
    if (-not $hermesBin) {
        Set-Status "hermes" "FAIL" "IRA_USE_HERMES on but 'hermes' not found (set IRA_HERMES_BIN)"
    } elseif (Test-HermesOneShot $hermesBin $ReadyTimeoutSec) {
        Set-Status "hermes" "OK" "hermes -z responded ($hermesBin)"
    } else {
        Set-Status "hermes" "FAIL" "hermes -z smoke failed/timed out ($hermesBin)"
    }
} else {
    Set-Status "hermes" "WARN" "IRA_USE_HERMES not enabled (Ollama-direct engine)"
}

# ── 5. Supertonic TTS (verify the on-device voice engine is importable) ─────────
# The API also pre-warms Supertonic on startup; this just surfaces a missing install
# now. Voice degrades gracefully (/voice/say -> 503), so a miss is WARN, not fatal.
try {
    & python -c "import supertonic" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Set-Status "supertonic" "OK" "import supertonic (TTS ready)" }
    else { Set-Status "supertonic" "WARN" "supertonic not importable — /voice/say degrades (pip install supertonic)" }
} catch { Set-Status "supertonic" "WARN" "could not run python to check supertonic" }

# ── 6. Web-research backends (optional — research fails soft) ──────────────────
$searxng = (Get-EnvOr "SEARXNG_URL" "http://localhost:8888").TrimEnd("/")
if (Test-Http "$searxng/" ) { Set-Status "searxng" "OK" $searxng }
else { Set-Status "searxng" "WARN" "down ($searxng) — web search disabled, research fails soft" }

$crawl4ai = (Get-EnvOr "CRAWL4AI_URL" "http://localhost:11235").TrimEnd("/")
if (Test-Http "$crawl4ai/health") { Set-Status "crawl4ai" "OK" $crawl4ai }
else { Set-Status "crawl4ai" "WARN" "down ($crawl4ai) — web reader disabled, research fails soft" }

# ── 7. IRA backend (uvicorn) ──────────────────────────────────────────────────
$apiPort = [int](Get-EnvOr "IRA_API_PORT" "8000")
if (-not (Test-Http "http://127.0.0.1:$apiPort/health")) {
    Start-Process -FilePath "python" `
        -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","$apiPort" `
        -WorkingDirectory $iraDir -WindowStyle Hidden -ErrorAction SilentlyContinue
}
if (Wait-Until { Test-Http "http://127.0.0.1:$apiPort/health" } $ReadyTimeoutSec) { Set-Status "ira-api" "OK" "http://127.0.0.1:$apiPort" }
else { Set-Status "ira-api" "FAIL" "no /health on $apiPort" }

# ── 8. IRA frontend (Next) ────────────────────────────────────────────────────
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
