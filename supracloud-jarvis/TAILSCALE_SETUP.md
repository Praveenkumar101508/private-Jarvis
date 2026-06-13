# Phone access over Tailscale (HTTPS) — IRA on your phone, privately

Reach IRA from your phone (even on cellular) without exposing a single port to the
public internet. **HTTPS is mandatory:** mobile browsers only grant microphone access
(`getUserMedia`) in a *secure context*. A plain `http://<tailnet-ip>` URL will load the
UI but the mic silently fails. `tailscale serve` gives you a valid `*.ts.net`
certificate, so the PWA + voice loop work on the phone.

> Sovereignty: traffic stays inside your tailnet (WireGuard, end-to-end). Nothing is
> published to the internet. Do **not** use `tailscale funnel` (that *is* public).

## 1. Install Tailscale (both devices, same tailnet)

- **Shadow box (Windows):** install from <https://tailscale.com/download>, sign in.
  Note the machine name → its MagicDNS host is `https://<shadow-name>.<tailnet>.ts.net`.
- **Phone:** install the Tailscale app (App Store / Play Store), sign in to the **same**
  account so both devices share the tailnet.

Verify: `tailscale status` on the box lists the phone; `tailscale cert <shadow-name>.<tailnet>.ts.net` succeeds (provisions the HTTPS cert).

## 2. Start IRA bound to localhost (NOT the public interface)

Run the stack as usual — uvicorn on `127.0.0.1:8000`, the frontend on `127.0.0.1:3000`
(`start-ira.ps1` already binds uvicorn to `127.0.0.1`):

```powershell
pwsh -File .\start-ira.ps1
```

Keep the services on `localhost` — `tailscale serve` proxies to them, so there's no
need to bind to the Tailscale IP and no port is ever open to the internet. Make sure
the Windows firewall does **not** forward 3000/8000 publicly.

## 3. Serve over HTTPS with `tailscale serve` (path routing)

The browser calls `/api`, `/auth`, `/health` **same-origin**, so route those paths to
the API and everything else to the frontend, all under one HTTPS origin:

```powershell
# API + auth + health -> uvicorn (8000)
tailscale serve --bg --set-path /api    http://127.0.0.1:8000/api
tailscale serve --bg --set-path /auth   http://127.0.0.1:8000/auth
tailscale serve --bg --set-path /health http://127.0.0.1:8000/health
# everything else -> the Next.js frontend (3000)
tailscale serve --bg http://127.0.0.1:3000

tailscale serve status   # confirm the routes + the https://<shadow>.<tailnet>.ts.net URL
```

> `tailscale serve` flag syntax varies by version; if `--set-path` isn't recognised,
> run `tailscale serve --help` and use the path-handler form for your version. The goal
> is: `/` → :3000, and `/api` `/auth` `/health` → :8000, under one `https://…ts.net`.

Because everything is same-origin, you do **not** need `NEXT_PUBLIC_API_BASE`. Set it
only if you choose to serve the API on a *different* host than the frontend.

## 4. Tell IRA the phone origin is allowed (CORS)

Set the Tailscale host so the backend allows the phone's HTTPS origin:

```
IRA_TS_HOST=shadow.<tailnet>.ts.net      # CORS allows https://<that host>
# Only if API and frontend are on different hosts:
# NEXT_PUBLIC_API_BASE=https://api.<tailnet>.ts.net
```

Restart the API after changing `.env`.

## 5. Install the PWA on the phone

1. On the phone, open `https://<shadow-name>.<tailnet>.ts.net` (valid cert → mic allowed).
2. **Add to Home Screen** (Android Chrome: install prompt; iPhone Safari: Share → Add to
   Home Screen). Launch it full-screen.
3. **Push-to-talk:** hold the big mic button, speak, release. (Wake word can't run
   backgrounded on iOS — PTT is the reliable phone path. Android also supports wake/clap
   in the foreground.)

## Acceptance

From a phone on **cellular** (not your home Wi-Fi): open the HTTPS PWA over Tailscale →
push-to-talk → IRA replies in voice → and a **voice coding request** ("fix the typo in
README") runs on the box and IRA speaks the outcome. No port is exposed publicly.

> Renting a GPU server / public deployment is a **separate, later playbook** — this is
> local + tailnet only.
