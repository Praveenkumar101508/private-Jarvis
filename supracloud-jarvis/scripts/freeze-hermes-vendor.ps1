# freeze-hermes-vendor.ps1 — Phase 6: (re)populate + verify the frozen Hermes vendor copy.
#
# Downloads the pinned hermes-agent wheel into supracloud-jarvis/hermes-vendor/ and verifies
# its sha256 against CHECKSUMS.txt. The wheel is gitignored, so this makes the DR / certified
# copy reproducible from the committed checksum. Bump both the pin and $expected together,
# deliberately, when upgrading.
$ErrorActionPreference = "Stop"

$pin      = "hermes-agent==0.15.2"
$expected = "1a062a3813de8998021a290abaf18489a5c009717b1569855b617ff2caef4b76"
$vendor   = Join-Path $PSScriptRoot "..\hermes-vendor"

python -m pip download $pin --no-deps -d $vendor | Out-Null
$whl = Get-ChildItem (Join-Path $vendor "hermes_agent-0.15.2*.whl") | Select-Object -First 1
if (-not $whl) { throw "wheel not downloaded into $vendor" }

$actual = (Get-FileHash $whl.FullName -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "CHECKSUM MISMATCH: got $actual expected $expected" }
Write-Host "OK: $($whl.Name) verified (sha256 $expected)"
