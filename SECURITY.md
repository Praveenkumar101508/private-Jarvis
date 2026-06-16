# Security Policy

## Threat Model

SupraCloud IRA is a **single-owner personal AI assistant**. The threat model is:

| Actor | Trust Level | What they can do |
|---|---|---|
| Owner (Praveen) | Full trust | All features, all data, all system commands |
| Authenticated users (future) | Partial trust | Chat, search, document analysis only |
| Unauthenticated requests | Zero trust | Blocked at nginx + FastAPI |
| LLM-generated content | Untrusted input | Sandboxed, no auto-deploy |
| Webhooks (Cal.com, external) | Signed only | Verified via HMAC-SHA256 |

## Authentication

- **Primary**: JWT Bearer tokens (HS256); short-lived access token (30 min) + refresh token (7 days), both issued at `POST /auth/token`; jti-based per-token revocation on logout; per-user revoke-all by bumping a Redis token version counter (invalidates all outstanding access tokens instantly)
- **Two-factor**: TOTP (time-based one-time password); enrol at `POST /auth/totp/enroll`; once a secret is enrolled and enabled, login at `/auth/token` refuses the token if a valid TOTP code is not supplied; TOTP failures count toward account lockout
- **Brute-force**: per-account progressive lockout — 5 consecutive failures trigger a 15-minute lock, escalating to a 24-hour cap; per-IP rate limit (5 req/min) enforced at the login endpoint
- **Voice**: ECAPA-TDNN biometric speaker verification (cosine similarity ≥ 0.75)
- **Service-to-service**: Long-lived JWT with `sub=ira-voice` for voice pipeline
- **Dev mode**: All auth bypassed — NEVER enable `DEV_MODE=true` in production

## Sensitive Data

IRA stores the following sensitive data:
- Conversation history (PostgreSQL `messages` table)
- Voice biometric profile (PostgreSQL `voice_profiles` table — 192-dim embedding)
- Memory embeddings (PostgreSQL `memory_embeddings` table)
- Task and reminder data

None of this data leaves your server unless you explicitly configure Replicate, Apify, or Telegram integrations.

## Owner-Gated Domains

The biometric gate blocks non-owner access to:
- Security logs, system credentials, .env contents
- Personal calendar, email, contact information
- Financial data
- Database schema and internal architecture
- Admin actions (user management, backup restore)

## Known Limitations

- Biometric voice gate requires enrolment — new installations have no voice owner profile
- Replicate, Apify, and Telegram integrations send data to third-party services when configured
- Computer use (Playwright) runs in a container with `--no-sandbox` — isolate from sensitive data

## Reporting Security Issues

This is a personal project. If you find a security issue, please open a private GitHub issue or email the owner directly.

## Security Checklist (Before Production Deployment)

- [ ] `DEV_MODE=false` in `.env`
- [ ] Strong `IRA_SECRET_KEY` (run: `openssl rand -hex 32`)
- [ ] Strong `IRA_ADMIN_PASSWORD` (16+ chars, mixed case + symbols)
- [ ] `OWNER_NAME` set to your real name
- [ ] TLS certificate configured in nginx
- [ ] `IRA_DOMAIN` set to your actual domain
- [ ] Telegram or email notifications configured for alerts
- [ ] Voice profile enrolled at `POST /api/v1/voice/enroll`
- [ ] TOTP enrolled for admin login (`POST /auth/totp/enroll`, then verify with `POST /auth/totp/verify`)
- [ ] `.env` file not committed to git (verify: `git ls-files .env`)
