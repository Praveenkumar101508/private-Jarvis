# IRA mobile app (Expo / React Native)

The phone client for IRA (#3). It talks to your IRA box **only over a private
Tailscale mesh** (see `../ira/docs/MOBILE_TAILSCALE.md`) and authenticates with the
existing JWT. Connectivity (Tailscale: my pick), framework (Expo: real push), and
task model (execute-ASAP, approval-gated) are the three decisions this implements.

> ⚠️ **Not validated in CI.** This is a JS/TS Expo app — it cannot be run or tested
> in the Python backend's sandbox. Build and run it on your machine with the
> Expo/React Native toolchain. The backend it depends on **is** fully tested.

## What's here
- `src/config.ts` — API base URL (set `expo.extra.iraApiBase` in `app.json` to your
  `https://shadow.<tailnet>.ts.net`).
- `src/auth.ts` — JWT stored in the OS secure store.
- `src/api.ts` — typed client for `/auth/token` + the `/mobile/*` contract.
- `src/push.ts` — request permission, get the Expo push token, register it
  (`POST /mobile/devices`).
- `App.tsx` — login → home (connectivity, enable notifications, the gated
  "send demo email" flow showing confirmation_required → approve, recent tasks).

## Run it
```bash
cd supracloud-jarvis/mobile
npm install
# point at your box: edit app.json -> expo.extra.iraApiBase
npm run tsc        # typecheck
npx expo start     # open in Expo Go / a dev build on your phone (same tailnet)
```

## Backend flags to enable (on the box)
```bash
export IRA_MOBILE_PUSH_ENABLED=true     # so "task done" pushes reach the phone
# (Tailscale + IRA_TS_HOST per ../ira/docs/MOBILE_TAILSCALE.md)
```

## Notes / next
- **Approval gate is honored**: side-effecting tasks (e.g. `email`) return
  `confirmation_required`; the app shows the preview and only runs on explicit
  approve — a tap can't silently fire an outbound action.
- Natural extensions: a `/ws/brain` chat screen (bearer.<JWT> subprotocol),
  richer task types, refresh-token handling via `/auth/refresh`.
