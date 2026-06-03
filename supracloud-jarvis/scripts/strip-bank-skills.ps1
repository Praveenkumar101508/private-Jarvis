# strip-bank-skills.ps1 — Phase 6 (bank-facing build).
#
# Removes red-team / jailbreak / safety-removal skills from the Hermes skill set so the
# gateway never loads them. Moves them to ~/.hermes/skills_disabled/ (REVERSIBLE — move
# back to re-enable). Run once after `hermes` install, then restart `hermes gateway`.
#
# Disallowed in a regulated-finance build:
#   red-teaming            -> contains `godmode` (jailbreak / unrestricted mode)
#   mlops/inference/obliteratus -> model "abliteration" (strips safety alignment)
$ErrorActionPreference = "Stop"

$skills   = Join-Path $HOME ".hermes\skills"
$disabled = Join-Path $HOME ".hermes\skills_disabled"
New-Item -ItemType Directory -Path $disabled -Force | Out-Null

$BLOCK = @("red-teaming", "mlops\inference\obliteratus")

foreach ($rel in $BLOCK) {
    $src = Join-Path $skills $rel
    if (Test-Path $src) {
        $dst = Join-Path $disabled ($rel -replace '[\\/]', '__')
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
        Move-Item $src $dst -Force
        Write-Host "disabled: $rel"
    } else {
        Write-Host "already absent: $rel"
    }
}
Write-Host "Bank-build skill strip complete. Restart 'hermes gateway' to reload the skill set."
