# harden-gateway.ps1 — Phase 7.1: pre-cutover security hardening (reproducible + reversible).
#
# Two fixes that MUST be in place before IRA_USE_HERMES is ever flipped ON:
#   1. Lock Ollama to localhost — otherwise the raw model is reachable on the network
#      and BYPASSES the gateway, biometric gate, and router.
#   2. Make the Hermes API-server agent REASONING-ONLY — remove file/shell/web/exec/
#      delegation toolsets at the CONFIG level (IRA runs every real tool itself). This
#      closes the security-skill over-reach (it had tried to read /var/log/auth.log) at
#      the source, not merely via the prompt directive in skills/_common.py.
#
# Idempotent. Re-run after any `hermes` install/update (a fresh install resets tool config).
$ErrorActionPreference = "Stop"

$hermes = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\hermes.exe"
if (-not (Test-Path $hermes)) { throw "hermes.exe not found at $hermes" }

# --- 1. Ollama -> localhost only ---
setx OLLAMA_HOST 127.0.0.1 | Out-Null
Get-Process ollama* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$t = 0
while ((Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue) -and $t -lt 25) { Start-Sleep -Milliseconds 200; $t++ }
$env:OLLAMA_HOST = "127.0.0.1"
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
$t = 0
while (-not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue) -and $t -lt 40) { Start-Sleep -Milliseconds 300; $t++ }
$bind = (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).LocalAddress
Write-Host "OK: Ollama bound to $bind:11434 (expect 127.0.0.1; was :: / 0.0.0.0)."

# --- 2. Reasoning-only gateway: the api_server agent needs ZERO tools (IRA runs every real
#        tool itself). Disabling only host/exec/network left todo/skills/memory enabled, which
#        BLED into reasoning (7.3 live verification: architect agents referenced a Hermes "task
#        list" / SKILL.md instead of answering). Disable the FULL toolset so it purely reasons. ---
$toolsets = @(
    "file", "terminal", "code_execution", "web", "browser", "delegation", "computer_use",
    "vision", "image_gen", "tts", "skills", "todo", "memory", "session_search", "clarify", "cronjob", "messaging"
)
& $hermes tools disable --platform api_server @toolsets
Write-Host "OK: api_server agent is reasoning-only (ZERO toolsets enabled)."
Write-Host "Verify: hermes tools list --platform api_server   (expect no 'enabled' lines)"
Write-Host "Undo:   hermes tools enable --platform api_server <toolset> ..."

# --- 3. Nginx gateway hardening (P1.3) ---
# Verify the hardened nginx.conf is in place and reload nginx if it is running.
# Checks for the P1.3 markers: slow-loris timeouts, perip conn limit, method allowlist.
$nginxConf = Join-Path $PSScriptRoot "..\future-scale\nginx\nginx.conf.template"
if (Test-Path $nginxConf) {
    $content = Get-Content $nginxConf -Raw
    $checks = @{
        "slow-loris client_body_timeout"  = "client_body_timeout"
        "slow-loris client_header_timeout"= "client_header_timeout"
        "perip connection limit"          = "zone=perip"
        "HTTP method allowlist"           = "request_method"
        "HSTS preload"                    = "preload"
    }
    $ok = $true
    foreach ($desc in $checks.Keys) {
        if ($content -notmatch [regex]::Escape($checks[$desc])) {
            Write-Warning "nginx config MISSING: $desc  (expected string: $($checks[$desc]))"
            $ok = $false
        }
    }
    if ($ok) { Write-Host "OK: hardened nginx.conf.template passes all P1.3 checks." }

    # Reload nginx if Docker is running the container
    $nginxContainer = docker ps --filter "name=nginx" --format "{{.Names}}" 2>$null | Select-Object -First 1
    if ($nginxContainer) {
        docker exec $nginxContainer nginx -t 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            docker exec $nginxContainer nginx -s reload
            Write-Host "OK: nginx reloaded in container '$nginxContainer'."
        } else {
            Write-Warning "nginx -t failed — config not reloaded. Fix errors above."
        }
    } else {
        Write-Host "INFO: nginx container not running — skipping reload (deploy the config manually)."
    }
} else {
    Write-Warning "nginx.conf.template not found at $nginxConf — skipping nginx checks."
}
