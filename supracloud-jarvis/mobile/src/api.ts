// Thin client for IRA's mobile contract. All calls go to the box over Tailscale
// (HTTPS) and carry the JWT. Endpoints verified against the backend:
//   POST /auth/token            (OAuth2 form: username, password) -> { access_token }
//   GET  /mobile/ping
//   POST /mobile/devices        { token, platform }
//   POST /mobile/tasks          { type, params, confirm_token? }
//   GET  /mobile/tasks
//   GET  /mobile/tasks/{id}
import { API_BASE } from "./config";
import { getToken } from "./auth";

async function authHeaders(): Promise<Record<string, string>> {
  const t = await getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function asJson(r: Response) {
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText} ${detail}`.trim());
  }
  return r.json();
}

export async function login(username: string, password: string): Promise<string> {
  // OAuth2PasswordRequestForm expects form-encoded fields.
  const body = new URLSearchParams({ username, password }).toString();
  const r = await fetch(`${API_BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await asJson(r);
  return data.access_token as string;
}

export async function ping() {
  return asJson(await fetch(`${API_BASE}/mobile/ping`, { headers: await authHeaders() }));
}

export async function registerDevice(token: string, platform: string) {
  return asJson(
    await fetch(`${API_BASE}/mobile/devices`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ token, platform }),
    }),
  );
}

export interface TaskResult {
  status: "queued" | "confirmation_required";
  task?: { id: string; type: string; status: string };
  token?: string;
  preview?: string;
  expires_in?: number;
}

export async function submitTask(
  type: string,
  params: Record<string, unknown>,
  confirmToken?: string,
): Promise<TaskResult> {
  return asJson(
    await fetch(`${API_BASE}/mobile/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ type, params, confirm_token: confirmToken ?? null }),
    }),
  );
}

export async function listTasks() {
  return asJson(await fetch(`${API_BASE}/mobile/tasks`, { headers: await authHeaders() }));
}
