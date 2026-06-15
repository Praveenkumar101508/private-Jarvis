# cortex-vendor/ — frozen Cortex copy (DO NOT EDIT)

**Frozen, checksummed copy of `hermes-agent==0.15.2`** for disaster recovery and the
certified bank build. Cortex runs **out-of-process** (installed natively under
`%LOCALAPPDATA%\cortex`, NOT in IRA's venv), so it is deliberately **not** in
`ira/requirements.txt`; this directory is the sovereign fallback if upstream ever
disappears or changes license — you keep the MIT-licensed 0.15.2 forever.

- `CHECKSUMS.txt` — the pinned version + the wheel's sha256 (committed; verifiable).
- The wheel (`*.whl`, ~10.8 MB) is **gitignored** (kept on-machine for DR, not in git history).
  Run `scripts/freeze-cortex-vendor.ps1` to (re)download + verify it into this dir.

Regenerate only via a deliberate, audited version bump (update the pin **and** the sha256
in `CHECKSUMS.txt` / `freeze-cortex-vendor.ps1` together). Never edit anything here.
