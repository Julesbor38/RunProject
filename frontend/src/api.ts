import { apiUrl, authHeader, authInit, isNative, setSessionToken } from "./native";

/** Called when the session is missing or expired (set by auth.ts: shows the login screen). */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

/** fetch() for /api: the session (cookie, or token in the native app), and a 401 brings the login screen back. */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(apiUrl(input), authInit(init));
  if (r.status === 401 && !input.startsWith("/api/auth/")) {
    onUnauthorized();
    throw new Error("connexion requise");
  }
  return r;
}

async function errorText(r: Response): Promise<string> {
  const detail = await r.json().catch(() => null);
  return typeof detail?.detail === "string" ? detail.detail : `erreur ${r.status}`;
}

export type Sport = "run" | "trail_run" | "hike";
export type LngLat = [number, number];

export interface ActivityFeature {
  type: "Feature";
  id: number;
  geometry: { type: "MultiLineString"; coordinates: LngLat[][] };
  properties: {
    source: string;
    key: string; // stable across re-imports (Strava id or file name): ratings are attached to it
    sport: Sport | null;
    name: string | null;
    start: string | null;
    distance_m: number;
    ascent_m: number;
    duration_s: number | null;
  };
}

export interface ActivityCollection {
  type: "FeatureCollection";
  features: ActivityFeature[];
  stats: { activities: number; no_gps: number; duplicates: number; errors: string[] };
}

export interface Preferences {
  nature: number;
  avoid_traffic: number;
  lit: number;
  familiarity: number;
  avoid_steps: number;
  hills: number;
}

export interface RouteFeature {
  type: "Feature";
  id: number;
  geometry: { type: "LineString"; coordinates: number[][] }; // [lon, lat, ele?]
  properties: {
    route_id: string; // kept by the server: GET gpxUrl(route_id)
    name: string;
    gpx_filename: string; // ASCII, ends in .gpx
    distance_m: number;
    nature: number;
    lit: number;
    busy_roads: number;
    familiar: number;
    repeated: number;
    ascent_m: number;
    descent_m: number;
    ele_min: number | null;
    ele_max: number | null;
    profile: [number, number][]; // [distance_m, elevation_m]
    in_ascent_range?: boolean;
    petals: number; // loops from the start the route is made of
  };
}

export interface RouteCollection {
  type: "FeatureCollection";
  features: RouteFeature[];
  elevation: boolean;
  warning?: string; // some OSM tiles could not be downloaded
}

export async function fetchActivities(): Promise<ActivityCollection> {
  const r = await apiFetch("/api/activities");
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function fetchRoutes(
  body: {
    start: LngLat;
    end?: LngLat;
    distance_km?: number;
    ascent_min_m?: number;
    ascent_max_m?: number;
    preferences: Preferences;
    request_id?: string;
    flat?: boolean; // the flattest routes, possibly several small loops (instead of a D+ range)
  },
  signal?: AbortSignal,
): Promise<RouteCollection> {
  const r = await apiFetch("/api/routes", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export interface RoutingStatus {
  tiles_total: number;
  tiles_cached: number;
  running: boolean;
  error: string | null;
}

export async function fetchRoutingStatus(): Promise<RoutingStatus> {
  const r = await apiFetch("/api/routing/status");
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export interface RouteProgress {
  stage: "start" | "download_ends" | "download" | "graph" | "routes";
  done: number;
  total: number;
  cancelled: boolean;
}

/** Progress of a generation started with this `request_id`, or null once it is over. */
export async function fetchRouteProgress(requestId: string): Promise<RouteProgress | null> {
  const r = await apiFetch(`/api/routes/${encodeURIComponent(requestId)}/progress`);
  return r.ok ? r.json() : null;
}

export async function cancelRoute(requestId: string): Promise<void> {
  await apiFetch(`/api/routes/${encodeURIComponent(requestId)}/cancel`, { method: "POST" });
}

/** The GPX of a generated route, served as a .gpx download (application/gpx+xml, attachment). */
export const gpxUrl = (routeId: string) => `/api/routes/${encodeURIComponent(routeId)}/gpx`;

// --- account ---

export async function currentUser(): Promise<string | null> {
  const r = await fetch(apiUrl("/api/auth/me"), authInit());
  return r.ok ? (await r.json()).user : null;
}

/** Log in (or sign up): the native app asks for the session token, the web gets the cookie. */
async function openSession(path: string, username: string, password: string): Promise<string> {
  const r = await fetch(
    apiUrl(path),
    authInit({
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password, token: isNative() }),
    }),
  );
  if (!r.ok) throw new Error(await errorText(r));
  const body = await r.json();
  if (body.token) setSessionToken(body.token);
  return body.user;
}

export const login = (username: string, password: string) => openSession("/api/auth/login", username, password);

/** Create an account (its data starts empty); logged in on success. */
export const signup = (username: string, password: string) => openSession("/api/auth/signup", username, password);

export async function signupOpen(): Promise<boolean> {
  const r = await fetch(apiUrl("/api/auth/options")).catch(() => null);
  return r?.ok ? (await r.json()).signup : false;
}

export async function logout(): Promise<void> {
  await fetch(apiUrl("/api/auth/logout"), authInit({ method: "POST" })).catch(() => null);
  setSessionToken(null);
}

// --- ratings ---

export interface Criterion {
  key: string;
  label: string;
}

export interface Rating {
  scores: Record<string, number>; // criterion -> 1..5
  comment: string;
  updated: number;
}

export async function fetchRatings(): Promise<{ criteria: Criterion[]; ratings: Record<string, Rating> }> {
  const r = await apiFetch("/api/ratings");
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function saveRating(key: string, scores: Record<string, number>, comment: string): Promise<Rating> {
  const r = await apiFetch(`/api/ratings/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scores, comment }),
  });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function deleteRating(key: string): Promise<void> {
  const r = await apiFetch(`/api/ratings/${encodeURIComponent(key)}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await errorText(r));
}

// --- adding activities ---

export interface ImportStatus {
  state: "idle" | "running" | "done" | "error";
  files?: number;
  new?: string[]; // keys of the activities the import added
  activities?: number;
  message?: string;
}

/** Upload with progress (fetch has no upload progress): resolves once the server stored the files. */
export function uploadImport(files: File[], onProgress: (fraction: number) => void): Promise<ImportStatus> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("/api/import"));
    for (const [k, v] of Object.entries(authHeader())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status === 401) {
        onUnauthorized();
        return reject(new Error("connexion requise"));
      }
      let body: { detail?: string } & ImportStatus;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        return reject(new Error(`erreur ${xhr.status}`));
      }
      if (xhr.status >= 400) reject(new Error(typeof body.detail === "string" ? body.detail : `erreur ${xhr.status}`));
      else resolve(body);
    };
    xhr.onerror = () => reject(new Error("envoi interrompu (réseau)"));
    xhr.send(form);
  });
}

export async function fetchImportStatus(): Promise<ImportStatus> {
  const r = await apiFetch("/api/import/status");
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}
