# IRA Portable — stop the stack (Windows / PowerShell).
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$EnvFile = if ($env:IRA_ENV_FILE) { $env:IRA_ENV_FILE } else { Join-Path $Here ".env" }
$ComposeFile = Join-Path $Root "docker-compose.portable.yml"

if (-not (Test-Path $ComposeFile)) { Write-Error "ERROR: missing $ComposeFile"; exit 1 }
Write-Host ">> Stopping IRA portable stack"
docker compose --env-file $EnvFile -f $ComposeFile down
Write-Host ">> Stopped. (Data in ./data, ./logs, ./config is preserved.)"
