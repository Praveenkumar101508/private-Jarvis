/**
 * Thin API client for the IRA backend.
 * Browser calls go through the same origin (nginx proxies /api/ → ira-api).
 * Server-side calls use IRA_API_INTERNAL_URL for direct container-to-container
 * routing (bypasses nginx, lower latency).
 */

// L7: SSR uses IRA_API_INTERNAL_URL (set to http://localhost:8000 in .env.local
// for native/no-Docker dev; "ira-api:8000" remains the Docker default). The
// browser uses same-origin ("") -> next.config.js rewrites /api,/auth,/health
// to the local API, so no nginx is needed in local mode.
const INTERNAL =
  typeof window === "undefined"
    ? process.env.IRA_API_INTERNAL_URL || "http://ira-api:8000"
    : "";

function base() {
  return INTERNAL;
}

export async function apiFetch(
  path: string,
  init?: RequestInit,
  token?: string
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const res = await fetch(`${base()}${path}`, { ...init, headers });
  if (!res.ok) {
    throw new Error(`IRA API error ${res.status} on ${path}`);
  }
  return res;
}

export async function getToken(
  username: string,
  password: string
): Promise<string> {
  const form = new FormData();
  form.append("username", username);
  form.append("password", password);
  const res = await fetch(`${base()}/auth/token`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error("Authentication failed");
  const data = await res.json();
  return data.access_token as string;
}

export async function getHealth() {
  const res = await fetch(`${base()}/health`);
  return res.json();
}

export async function getTasks(token: string, status?: string) {
  const qs = status ? `?status=${status}` : "";
  const res = await apiFetch(`/api/v1/tasks${qs}`, {}, token);
  return res.json();
}

export async function createTask(
  token: string,
  title: string,
  options?: { description?: string; priority?: string; due_at?: string }
) {
  const res = await apiFetch(
    "/api/v1/tasks",
    { method: "POST", body: JSON.stringify({ title, ...options }) },
    token
  );
  return res.json();
}

export async function getLatestBriefing(token: string) {
  const res = await apiFetch("/api/v1/briefing/latest", {}, token);
  return res.json();
}

export async function triggerBriefing(token: string, type = "morning") {
  const res = await apiFetch(
    `/api/v1/briefing/now?briefing_type=${type}`,
    { method: "POST" },
    token
  );
  return res.json();
}
