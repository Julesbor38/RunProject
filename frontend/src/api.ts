export type Sport = "run" | "trail_run" | "hike";
export type LngLat = [number, number];

export interface ActivityFeature {
  type: "Feature";
  id: number;
  geometry: { type: "MultiLineString"; coordinates: LngLat[][] };
  properties: {
    source: string;
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
  };
}

export interface RouteCollection {
  type: "FeatureCollection";
  features: RouteFeature[];
  elevation: boolean;
  warning?: string; // some OSM tiles could not be downloaded
}

/** Pieces of the tracks with the number of distinct activities that went along them. */
export interface FrequencyCollection {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    geometry: { type: "LineString"; coordinates: LngLat[] };
    // `activity`: one activity that went there; per sport: whether activities of that sport did.
    properties: { activity: number; passes: number } & Record<Sport, boolean>;
  }[];
  max_passes: number;
  levels: number[]; // lower bounds of the pass levels
}

export async function fetchFrequency(): Promise<FrequencyCollection> {
  const r = await fetch("/api/frequency");
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function fetchActivities(): Promise<ActivityCollection> {
  const r = await fetch("/api/activities");
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
  },
  signal?: AbortSignal,
): Promise<RouteCollection> {
  const r = await fetch("/api/routes", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `erreur ${r.status}`);
  }
  return r.json();
}

export interface RoutingStatus {
  tiles_total: number;
  tiles_cached: number;
  running: boolean;
  error: string | null;
}

export async function fetchRoutingStatus(): Promise<RoutingStatus> {
  const r = await fetch("/api/routing/status");
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
  const r = await fetch(`/api/routes/${encodeURIComponent(requestId)}/progress`);
  return r.ok ? r.json() : null;
}

export async function cancelRoute(requestId: string): Promise<void> {
  await fetch(`/api/routes/${encodeURIComponent(requestId)}/cancel`, { method: "POST" });
}

/** The GPX of a generated route, served as a .gpx download (application/gpx+xml, attachment). */
export const gpxUrl = (routeId: string) => `/api/routes/${encodeURIComponent(routeId)}/gpx`;
