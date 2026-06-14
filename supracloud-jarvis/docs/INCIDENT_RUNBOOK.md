# IRA Incident Runbook

**Owner:** System owner (see `.env` → `IRA_OWNER_NAME`)  
**Last reviewed:** 2026-06-14  
**Applies to:** IRA v2 on SupraCloud (local Shadow PC deployment)

---

## Table of Contents

1. [Severity levels](#1-severity-levels)
2. [Quick reference — manual playbook commands](#2-quick-reference--manual-playbook-commands)
3. [Break-glass: emergency access when normal auth is broken](#3-break-glass-emergency-access-when-normal-auth-is-broken)
4. [Event-by-event response playbook](#4-event-by-event-response-playbook)
5. [Recovery procedures after confirmed compromise](#5-recovery-procedures-after-confirmed-compromise)
6. [Log locations and notification channels](#6-log-locations-and-notification-channels)
7. [Redis key reference](#7-redis-key-reference)

---

## 1. Severity levels

| Severity | Response time | Examples |
|----------|--------------|---------|
| **CRITICAL** | Immediate | Canary token used, canary username login, canary path hit |
| **HIGH** | < 15 min | Account locked, SSRF block, brute force detected |
| **MEDIUM** | < 1 hour | Login failure, playbook triggered, slow Redis |
| **LOW / INFO** | Next business day | Routine events, reflection notes |

---

## 2. Quick reference — manual playbook commands

These run inside the IRA API process. Easiest via `psql` or a quick Python one-liner.

### Block an IP (1 hour)
```bash
# Via psql — inserts a security event and triggers the playbook audit trail
# Preferred: use the Python shell so the Redis key is set correctly
cd supracloud-jarvis/ira
python - <<'EOF'
import asyncio
from utils.playbooks import block_ip
asyncio.run(block_ip("1.2.3.4", ttl_seconds=3600))
EOF
```

### Block an IP (24 hours — for confirmed honeypot/canary hits)
```bash
python - <<'EOF'
import asyncio
from utils.playbooks import block_ip
asyncio.run(block_ip("1.2.3.4", ttl_seconds=86400))
EOF
```

### Unblock an IP
```bash
# Redis key: ira:blocked_ip:{ip}
redis-cli DEL "ira:blocked_ip:1.2.3.4"
```

### Rotate tokens for a user (invalidates ALL outstanding access tokens immediately)
```bash
python - <<'EOF'
import asyncio
from utils.playbooks import rotate_tokens
asyncio.run(rotate_tokens("admin"))
EOF
```

### Snapshot security logs to disk
```bash
python - <<'EOF'
import asyncio
from utils.playbooks import snapshot_logs
asyncio.run(snapshot_logs(label="manual-incident-2026-06-14"))
EOF
# Output file: $IRA_LOG_SNAPSHOT_DIR/ira-security-snapshot-manual-incident-*.json
# Default dir: /tmp/ira-logs/
```

### Clear account lockout
```bash
# Redis keys: ira:login_fails:{username}  ira:login_lock:{username}
redis-cli DEL "ira:login_fails:admin" "ira:login_lock:admin"
```

---

## 3. Break-glass: emergency access when normal auth is broken

Use when: you are locked out of the API and cannot obtain a normal JWT.

### 3a. Enable DEV_MODE (local only — never in production exposure)

1. Edit `.env`: set `DEV_MODE=true`
2. Restart the API: `docker compose restart ira-api` (or `uvicorn` if running bare)
3. All API calls now return the admin username without a token check
4. **Re-disable immediately after remediation**: set `DEV_MODE=false` and restart

> DEV_MODE is a local-only bypass. The API logs a WARNING on every request made in this mode. Never expose the port to the internet while DEV_MODE is active.

### 3b. Generate an emergency JWT directly

```bash
cd supracloud-jarvis/ira
python - <<'EOF'
from datetime import datetime, timedelta, timezone
import uuid
from jose import jwt
from config import get_settings
cfg = get_settings()
expire = datetime.now(timezone.utc) + timedelta(hours=1)
payload = {
    "sub": cfg.ira_admin_username,
    "exp": expire,
    "jti": str(uuid.uuid4()),
    "tok": "access",
    "ver": 0,
}
token = jwt.encode(payload, cfg.ira_secret_key, algorithm="HS256")
print(f"Bearer {token}")
print(f"Expires: {expire.isoformat()}")
EOF
```

Then use: `curl -H "Authorization: Bearer <token>" https://localhost/api/v1/...`

> Note: if per-user token version (`ira:token_ver:admin`) was bumped above 0, set `"ver"` in the payload to match or exceed the current Redis value. Check with: `redis-cli GET "ira:token_ver:admin"`

### 3c. Direct database access

```bash
# Connect as the Postgres user
docker compose exec postgres psql -U jarvis -d ira

-- View recent security events
SELECT created_at, severity, event_type, source_ip, description
FROM security_events
ORDER BY created_at DESC
LIMIT 50;

-- View current IP blocks via Redis (not Postgres)
-- Use: redis-cli KEYS "ira:blocked_ip:*"
```

### 3d. Bypass account lockout in Redis

If the admin account is locked due to automated lockout:
```bash
redis-cli DEL "ira:login_lock:admin" "ira:login_fails:admin"
```

The lockout is fail-open: if Redis is down, logins are never blocked by lockout. Restart Redis if needed: `docker compose restart redis`

---

## 4. Event-by-event response playbook

Security events are stored in `security_events` (Postgres) and emitted to Telegram for HIGH/CRITICAL.

### 4.1 `canary_tripwire_hit` — Honeypot path accessed (CRITICAL)

**What happened:** An HTTP request hit one of the monitored honeypot paths (e.g. `/.env`, `/.git/config`, `/wp-admin`). No legitimate client should ever hit these paths.

**Automated response:** The source IP is automatically blocked for 24 hours via `run_security_playbooks`.

**Manual steps:**
1. Identify the source IP from the `source_ip` field in `security_events`
2. Check if the IP is already blocked: `redis-cli EXISTS "ira:blocked_ip:{ip}"`
3. If not blocked (e.g. Redis was down during the event): `block_ip("{ip}", ttl_seconds=86400)`
4. Review the canary path log for the full request headers and user agent
5. If the same IP hit multiple paths in a short window, consider a 7-day block
6. Snapshot logs for forensics: `snapshot_logs(label="canary-tripwire-{ip}")`

### 4.2 `canary_token_used` — Fake JWT token presented (CRITICAL)

**What happened:** The canary Bearer token (configured in `IRA_CANARY_TOKEN`) was presented to the API. This token is never given to any legitimate client — its only purpose is to detect credential theft or replay attacks.

**Automated response:** Source IP blocked for 24 hours.

**Manual steps:**
1. The token has been used — rotate `IRA_CANARY_TOKEN` immediately (generate a new one with `openssl rand -hex 32`)
2. Update `.env` with `IRA_CANARY_TOKEN=<new-value>` and restart the API
3. Investigate how the token could have been obtained (memory dump, log leak, env file exposure)
4. Check whether `IRA_SECRET_KEY` is still secret — if the token was obtained via an env leak, rotate all secrets (see §5)
5. Block the source IP permanently (7-day cap): `block_ip("{ip}", ttl_seconds=604800)`

### 4.3 `canary_username_login_attempt` — Ghost username used (CRITICAL)

**What happened:** A login attempt was made with the canary username (configured in `IRA_CANARY_USERNAME`). This username is never given to any legitimate client.

**Automated response:** Source IP blocked for 24 hours.

**Manual steps:**
1. The ghost username was used — check if it appeared in any logs, configs, or documentation that shouldn't be public
2. Block the source IP: `block_ip("{ip}", ttl_seconds=86400)`
3. If this coincides with other canary events, treat as active targeted attack — rotate `IRA_CANARY_USERNAME` and all secrets

### 4.4 `brute_force` — Multiple failed login attempts (HIGH)

**What happened:** The security monitor detected a pattern of repeated login failures from a source, or the account lockout threshold was exceeded.

**Automated response:** Source IP blocked for 1 hour.

**Manual steps:**
1. Verify the IP block is active: `redis-cli TTL "ira:blocked_ip:{ip}"`
2. If the attack is persistent, extend the block: `block_ip("{ip}", ttl_seconds=86400)`
3. Check the fail counter: `redis-cli GET "ira:login_fails:admin"`
4. If the admin account is locked: `redis-cli DEL "ira:login_lock:admin" "ira:login_fails:admin"`
5. Consider rotating the admin password in `.env` → `IRA_ADMIN_PASSWORD`

### 4.5 `account_locked` — Admin account locked out (HIGH)

**What happened:** The admin account exceeded `MAX_FAILURES` (5) consecutive failed login attempts within 15 minutes.

**Lock escalation:** 15 min → 30 min → 60 min → … → 24 h cap (exponential backoff).

**Manual steps:**
1. Clear the lock: `redis-cli DEL "ira:login_lock:admin" "ira:login_fails:admin"`
2. Check whether the login failures were from a known source IP and block it
3. Verify no active session was hijacked by reviewing recent successful logins in `security_events`

### 4.6 `ssrf_block` — Outbound SSRF attempt blocked (HIGH)

**What happened:** The egress guard (`channels/guard.py`) blocked a request that would have made an outbound HTTP call to a disallowed or internal-network destination.

**No automated IP block** (SSRF may be from prompt injection, not the client IP).

**Manual steps:**
1. Review the `description` in `security_events` for the blocked URL/host
2. If the request came from a user-controlled input (research/web tool), verify the prompt injection guard is working
3. If the URL was in the tool's own hardcoded config, that is a code bug — audit `channels/` for hardcoded URLs
4. If repeated SSRF attempts from the same IP, block it: `block_ip("{ip}", ttl_seconds=3600)`

### 4.7 `credential_smuggling` — Credentials in agent output (CRITICAL)

**What happened:** An LLM response or tool call contained content matching credential-smuggling patterns (keys, tokens, passwords in URLs or tool arguments).

**Manual steps:**
1. Review the raw content in `security_events.raw_log` to understand what was leaked
2. If actual secrets appeared in a response, rotate those secrets immediately (§5)
3. Review which agent/tool produced the response and add output filtering
4. Snapshot logs: `snapshot_logs(label="credential-smuggling")`

### 4.8 `disk_pressure` — Low disk space (HIGH)

**What happened:** `_check_system_resources()` in `worker/self_healing.py` detected disk usage > 90%.

**Automated response:** `snapshot_logs` is called with label `disk_pressure_auto` to preserve forensic logs before disk fills completely.

**Manual steps:**
1. Free disk space: clear old snapshot files in `$IRA_LOG_SNAPSHOT_DIR` (default `/tmp/ira-logs/`)
2. Clear old Docker images: `docker image prune -f`
3. Check Postgres WAL/log bloat: `docker compose exec postgres psql -c "SELECT pg_size_pretty(pg_database_size('ira'));"`

### 4.9 `redis_down` — Redis unreachable (CRITICAL for self-healing)

**What happened:** The self-healing worker cannot reach Redis.

**Impact:** Token revocation checks fail-open (existing revocations are not checked). IP blocks are not enforced. Account lockout is not applied.

**Manual steps:**
1. Restart Redis: `docker compose restart redis`
2. Verify: `redis-cli ping` → `PONG`
3. If data was lost, re-apply any active IP blocks manually
4. The lockout and revocation mechanisms resume automatically on Redis reconnect

---

## 5. Recovery procedures after confirmed compromise

Follow in order. Complete each step before proceeding to the next.

### Step 1 — Contain

```bash
# Block all external access (firewall or stop nginx)
docker compose stop nginx

# Take a forensic log snapshot before anything changes
cd supracloud-jarvis/ira
python - <<'EOF'
import asyncio
from utils.playbooks import snapshot_logs
asyncio.run(snapshot_logs(label="compromise-containment"))
EOF
```

### Step 2 — Rotate all secrets

```bash
# Generate new values
openssl rand -hex 32   # → IRA_SECRET_KEY (invalidates ALL JWTs)
openssl rand -hex 32   # → IRA_CANARY_TOKEN
openssl rand -hex 16   # → IRA_CANARY_USERNAME (use an unusual string)
openssl rand -hex 24   # → IRA_ADMIN_PASSWORD (also update IRA_ADMIN_PASSWORD_HASH)
openssl rand -hex 32   # → WEBHOOK_SECRET (if Telegram webhook is configured)
```

Edit `.env` with the new values. Never commit `.env` to git.

After updating `IRA_ADMIN_PASSWORD`, regenerate its bcrypt hash:
```bash
python - <<'EOF'
from api.middleware.auth import hash_password
print(hash_password("your-new-password-here"))
EOF
```
Set `IRA_ADMIN_PASSWORD_HASH` in `.env` to the output.

### Step 3 — Clear all Redis state

```bash
# Flush all IRA-namespaced Redis keys (token versions, blocks, locks, fail counters)
redis-cli KEYS "ira:*" | xargs redis-cli DEL

# Alternatively, flush the entire Redis DB if IRA is the sole tenant
redis-cli FLUSHDB
```

### Step 4 — Restart all services

```bash
docker compose down && docker compose up -d
```

Verify the API is healthy: `curl -k https://localhost/api/v1/health`

### Step 5 — Re-enable external access

```bash
docker compose start nginx
```

Confirm TLS is working and the new secrets are in effect by logging in with the new password.

### Step 6 — Post-incident review

1. Review `security_events` for the full timeline
2. Identify the initial access vector
3. Check git log for any unauthorized commits: `git log --since="48 hours ago" --all`
4. Verify the self-modification invariant is intact: no `git push` in `utils/auto_implement.py`
5. Update this runbook with any new indicators of compromise

---

## 6. Log locations and notification channels

### Security events database

```sql
-- All events, newest first
SELECT created_at, severity, event_type, source_ip, description
FROM security_events
ORDER BY created_at DESC
LIMIT 100;

-- Events by severity
SELECT * FROM security_events
WHERE severity IN ('critical', 'high')
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Unresolved events
SELECT * FROM security_events WHERE resolved = false
ORDER BY created_at DESC;
```

### Telegram notifications

HIGH and CRITICAL events are pushed to Telegram via `utils/security_events.py → _do_telegram_push()`. Configure:
- `TELEGRAM_BOT_TOKEN` — the bot token
- `TELEGRAM_CHAT_ID` — your personal or group chat ID

Test the notification channel:
```bash
python - <<'EOF'
import asyncio
from utils.security_events import emit_event
asyncio.run(emit_event("test_alert", "high", description="Runbook connectivity test"))
EOF
```

### Log snapshot files

Written to `$IRA_LOG_SNAPSHOT_DIR` (default `/tmp/ira-logs/`).  
Format: `ira-security-snapshot-{label}-{YYYYMMDDTHHMMSSz}.json`

To move snapshots to a persistent location before they are lost on container restart:
```bash
cp /tmp/ira-logs/*.json /persistent/path/ira-forensics/
```

### Application logs

```bash
# Live API logs
docker compose logs -f ira-api

# Worker (self-healing + security monitor)
docker compose logs -f ira-worker

# Filter for security-related log lines
docker compose logs ira-api | grep -E "(WARN|ERROR|CRITICAL|canary|blocked|locked|revoked)"
```

---

## 7. Redis key reference

| Key pattern | Purpose | Set by | TTL |
|------------|---------|--------|-----|
| `ira:blocked_ip:{ip}` | IP blocklist | `block_ip()` | 1 h default, max 7 days |
| `ira:login_fails:{username}` | Fail counter | `record_failure()` | 15 min sliding window |
| `ira:login_lock:{username}` | Account lock | `record_failure()` | 15 min → 24 h (escalating) |
| `ira:token_ver:{username}` | Token version | `rotate_tokens()` / `bump_token_version()` | No TTL (persistent) |
| `ira:revoked:{jti}` | Individual token revocation | `revoke_token()` | Remaining token TTL |

To inspect all IRA keys:
```bash
redis-cli KEYS "ira:*"
```

To check TTL on a specific key:
```bash
redis-cli TTL "ira:blocked_ip:1.2.3.4"    # seconds remaining (-1 = no TTL, -2 = gone)
```
