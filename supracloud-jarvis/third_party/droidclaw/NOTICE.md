# droidclaw — third-party (patterns adapted, not vendored)

- **Project:** droidclaw — an AI agent that controls an Android device
- **Upstream:** https://github.com/unitedbyai/droidclaw
- **License:** MIT

## What we adapted

IRA's experimental Android actuator (`ira/actions/android_actuator.py`) **adapts
the design** of droidclaw's screen-reading + recovery loop — re-implemented in
Python; **no TypeScript source is copied or vendored**:

- `src/sanitizer.ts` → `parse_ui_xml` / `filter_elements` / `compute_screen_hash`
  (uiautomator accessibility-tree → scored interactive elements).
- `src/kernel.ts` recovery logic → `RecoveryTracker` (stuck-loop / repetition
  detection).

It runs fully locally (adb + IRA's Ollama model), is **OFF by default**
(`android_actuator_enabled=False`), treats on-screen text as untrusted (wrapped +
injection-scanned), and gates actuation behind the approval guardrail.

## CVE-2026-10216 (we do NOT run their server)

droidclaw's `server/src/routes/pairing.ts` `claim` endpoint is vulnerable
(CWE-307, CVSS 2.9): it is public/tunnel-exposed and rate-limits only by the
spoofable `x-forwarded-for` header, allowing brute force of the 6-digit code.

We do not run that server. `ira/actions/android_pairing.py` is the only sanctioned
pairing path and closes the issue by construction:

1. **Loopback-only** (`assert_loopback`) — refuses any LAN/public/0.0.0.0 host,
   removing the remote attack vector.
2. **Non-spoofable rate limit** (`RateLimiter`/`PairingGuard`) — counts attempts
   against a fixed local key, not a client header, with a strict per-window cap.

MIT attribution is recorded here for license hygiene (R3).
