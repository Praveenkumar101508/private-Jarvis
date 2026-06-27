import Constants from "expo-constants";

// Base URL of your IRA box over Tailscale Serve (HTTPS). Override in app.json
// (expo.extra.iraApiBase) or here. See docs/MOBILE_TAILSCALE.md.
export const API_BASE: string =
  (Constants.expoConfig?.extra?.iraApiBase as string) ||
  "https://shadow.your-tailnet.ts.net";
