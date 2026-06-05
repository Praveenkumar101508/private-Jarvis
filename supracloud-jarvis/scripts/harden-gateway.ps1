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
