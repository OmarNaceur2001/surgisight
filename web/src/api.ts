/** API client. Access credentials stay in module memory; refresh uses an HttpOnly cookie. */
export type AuthPayload = { access_token: string; token_type: string; expires_in: number };
let accessToken: string | null = null;

const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function getAccessToken(): string | null {
  return accessToken;
}
export function apiBaseUrl(): string {
  return baseUrl;
}

async function decodeResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload.detail === "string" ? payload.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? response.json() : response.blob()) as Promise<T>;
}

async function refreshAccess(): Promise<boolean> {
  const response = await fetch(`${baseUrl}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    accessToken = null;
    return false;
  }
  const body = (await response.json()) as AuthPayload;
  accessToken = body.access_token;
  return true;
}

export async function restoreSession(): Promise<User | null> {
  if (!(await refreshAccess())) return null;
  try {
    return await apiRequest<User>("/auth/me", {}, false);
  } catch {
    accessToken = null;
    return null;
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await refreshAccess()) return apiRequest<T>(path, init, false);
  }
  return decodeResponse<T>(response);
}

export async function signIn(email: string, password: string): Promise<{ token: AuthPayload; user: User }> {
  const token = await apiRequest<AuthPayload>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
  setAccessToken(token.access_token);
  const user = await apiRequest<User>("/auth/me", {}, false);
  return { token, user };
}

export async function signOut(): Promise<void> {
  try {
    await apiRequest<void>("/auth/logout", { method: "POST" }, false);
  } finally {
    setAccessToken(null);
  }
}

export type User = { id: string; email: string; role: "admin" | "reviewer" | "researcher" | "viewer" };
export type LibraryVideo = {
  id: string; global_video_id: string; dataset: string; duration_s: number; fps: number;
  created_at: string; latest_run_id?: string | null; latest_run_status?: string | null;
  report_id?: string | null;
};
export type VideoDetails = {
  id: string; global_video_id: string; dataset: string; duration_s: number; fps: number;
  crop_offset: number[]; media_url: string; thumbnail_url: string; notice: string;
};
export type PhaseSegment = {
  label: string; name: string; start: number; end: number; conf: number; uncertain: boolean;
};
export type Report = {
  schema_version: string; video_id: string; dataset: string; duration_s: number;
  status: "DRAFT_PENDING_REVIEW" | "REVIEWED"; disclaimer: string;
  phases: PhaseSegment[]; tools: { tool: string; usage_s: number; pct: number }[];
  events: { type: string; t: number; conf: number; uncertain: boolean; evidence: string[] }[];
  triplet_highlights: { ivt_id: number; ivt_name: string; t: number; score: number; phase?: string | null }[];
  confidence_notes: string[]; models: Record<string, string>; summary?: string | null;
};
export type Analysis = {
  id: string; status: string; progress: number; stage: string; report_id?: string | null;
  model_versions: Record<string, string>; error?: string | null;
};
