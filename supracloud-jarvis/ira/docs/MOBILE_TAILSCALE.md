# Mobile access over Tailscale (sovereign, no public exposure)

This is the connectivity layer for the IRA mobile app (#3). The phone and the
Shadow box join one private [Tailscale](https://tailscale.com) mesh; IRA is reachable
only inside that mesh — never on the public internet. IRA's own auth (JWT), the
approval gate, and the egress guard still apply on top.

> Why Tailscale: a WireGuard-based private network with zero open inbound ports.
> If you want the coordination plane self-hosted too, run
> [headscale](https://github.com/juanfont/headscale) instead of Tailscale's hosted
> control server — the client setup below is otherwise identical.

## 1. Put both devices on the tailnet

On the **Shadow box** (where IRA runs):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4          # note the 100.x.y.z address
tailscale status         # confirm the box is online
```

On the **phone**: install the Tailscale app and sign in to the **same** tailnet.

## 2. Serve IRA over HTTPS inside the mesh

The mobile app needs a secure (HTTPS) origin — for the API, the WebSockets
(`/ws/brain`, `/ws/notifications`), and, if you use the browser mic, `getUserMedia`.
Tailscale Serve terminates TLS with a `*.ts.net` cert, no public exposure:

```bash
# IRA listening locally on :8000 (adjust to your run command/port)
tailscale serve --bg 8000
tailscale serve status   # shows https://shadow.<tailnet>.ts.net  -> 127.0.0.1:8000
```

Keep IRA bound to localhost (`127.0.0.1:8000`); Tailscale Serve is the only thing
in front of it, and only tailnet members can reach it.

## 3. Tell IRA about the Tailscale origin (CORS)

IRA already supports this — set the env var so the `*.ts.net` HTTPS origin is allowed:

```bash
export IRA_TS_HOST=shadow.<tailnet>.ts.net   # read in main.py → CORS allow_origins
```

(See `create_app()` in `main.py`: when `IRA_TS_HOST` is set, `https://<that host>` is
added to the CORS allowlist.)

## 4. Point the app at IRA + sign in

In the Expo app config set the base URL to `https://shadow.<tailnet>.ts.net`. The app
logs in via the existing auth endpoint to obtain a JWT, then calls:

- `GET  /mobile/ping` — connectivity/identity check
- `POST /mobile/devices` — register the Expo push token
- `POST /mobile/tasks` — submit an execute-ASAP task (confirmation flow for
  side-effecting types — see below)
- `GET  /mobile/tasks` / `GET /mobile/tasks/{id}` — task list / status + result

WebSockets (`/ws/brain`) authenticate with `Sec-WebSocket-Protocol: bearer.<JWT>`
(or `?token=` in dev).

## 5. Turn on mobile features (server side)

```bash
export IRA_MOBILE_PUSH_ENABLED=true     # enable Expo push ("task done → your phone")
# then register the device from the app: POST /mobile/devices {token: "ExponentPushToken[...]"}
```

## Security notes (defense in depth)

- **No public ports.** Don't port-forward; Tailscale Serve (not `tailscale funnel`)
  keeps everything inside the tailnet.
- **ACLs.** In the Tailscale admin (or headscale policy), restrict which nodes may
  reach the Shadow box so only your phone (and the box) can talk to IRA.
- **Auth still required.** Every `/mobile/*` route is owner-gated by JWT; the mesh is
  the network boundary, not the auth boundary.
- **Side-effecting tasks are gated.** `POST /mobile/tasks` with a side-effecting type
  (e.g. `email`) returns `confirmation_required` with a one-time token; nothing runs
  until the owner confirms — a phone tap can never silently fire an outbound action.
- **Egress guard** (`channels/guard.py`) and the **approval gate** (`utils/approval.py`)
  remain in force regardless of how a request arrives.
