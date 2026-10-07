/**
 * Getting a route's GPX on a phone without ever leaving or replacing the app's page (in the app added to the
 * iOS home screen, a download replaces it with a full-screen file preview that has no way back).
 *
 * 1. The system share sheet, over the app: the File is built in advance (as soon as the route is shown), so
 *    that the tap calls navigator.share synchronously (Safari refuses it once the tap's activation is lost).
 * 0. In the native iOS app (mobile/, Capacitor): its OpenIn plugin shows iOS's « Ouvrir dans… » menu, where
 *    the watch apps are listed (a web page can't show that menu).
 * 2. Fallback, when files can't be shared: a signed /dl/ link, outside the PWA scope (/app/), opened in a new
 *    window: iOS shows it over the app with its own « OK », never in place of the app.
 */
import { apiFetch, gpxUrl } from "./api";
import { debugLog, setGpxChecks } from "./debug";

/** Tried in this order: the first one the share sheet accepts is used. */
export const GPX_MIME_TYPES = ["application/gpx+xml", "application/xml", "text/xml", "application/octet-stream"];

/** canShare({files}) for each MIME type ("true", "false", "absent" or the error), and the first accepted file. */
export function shareableFile(data: BlobPart, filename: string): { file: File | null; checks: Record<string, string> } {
  const checks: Record<string, string> = {};
  let file: File | null = null;
  for (const type of GPX_MIME_TYPES) {
    const candidate = new File([data], filename, { type });
    let ok: string;
    try {
      ok = typeof navigator.canShare === "function" ? String(navigator.canShare({ files: [candidate] })) : "absent";
    } catch (e) {
      ok = `${(e as Error).name}: ${(e as Error).message}`;
    }
    checks[type] = ok;
    if (!file && ok === "true") file = candidate;
  }
  return { file, checks };
}

export interface PreparedGpx {
  ready: boolean; // the file and the link have been asked for and answered
  file: File | null; // null once ready: the share sheet takes no GPX here
  data64: string | null; // the GPX in base64, for the native app
  link: string | null; // signed /dl/ link (fallback)
  expires: number; // of the link (epoch s)
  failed: string | null;
  routeId: string;
}

/** Fetch the route's GPX and its signed link right away, so that a later tap needs no await. */
export function prepareGpx(routeId: string, filename: string): PreparedGpx {
  const out: PreparedGpx = { ready: false, file: null, data64: null, link: null, expires: 0, failed: null, routeId };
  const file = apiFetch(gpxUrl(routeId))
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`GPX : erreur ${r.status}`))))
    .then((data) => {
      if (nativeOpenIn()) out.data64 = toBase64(data);
      const { file: f, checks } = shareableFile(data, filename);
      setGpxChecks(filename, checks, f?.type ?? null);
      out.file = f;
    });
  const link = fetchLink(out);
  Promise.allSettled([file, link]).then((results) => {
    const errors = results.filter((r): r is PromiseRejectedResult => r.status === "rejected").map((r) => String(r.reason?.message ?? r.reason));
    out.failed = errors.length ? errors.join(" ; ") : null;
    if (errors.length) debugLog("préparation du GPX", out.failed!);
    out.ready = true;
  });
  return out;
}

function fetchLink(gpx: PreparedGpx): Promise<unknown> {
  return apiFetch(`/api/routes/${encodeURIComponent(gpx.routeId)}/link`, { method: "POST" })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`lien : erreur ${r.status}`))))
    .then((body: { url: string; expires: number }) => Object.assign(gpx, { link: body.url, expires: body.expires }));
}

/**
 * Called in the tap itself, with nothing awaited before. Returns what happened right away; the share
 * result arrives later through the callbacks (AbortError, i.e. the user closed the sheet: silence).
 */
export function sendGpx(
  gpx: PreparedGpx,
  on: { shared: () => void; failed: (error: string) => void },
): "sharing" | "opened" | "not-ready" | "unavailable" {
  if (gpx.file) {
    debugLog("partage", `${gpx.file.name} (${gpx.file.type})`);
    navigator.share({ files: [gpx.file] }).then(
      () => {
        debugLog("partage", "terminé");
        on.shared();
      },
      (e: Error) => {
        if (e.name === "AbortError") return debugLog("partage", "annulé (AbortError)");
        debugLog("partage : erreur", `${e.name}: ${e.message}`);
        on.failed(`${e.name}: ${e.message}`);
      },
    );
    return "sharing";
  }
  if (!gpx.ready) return "not-ready";
  return openLink(gpx) ? "opened" : "unavailable";
}

type CapacitorGlobal = {
  isNativePlatform?: () => boolean;
  nativePromise?: (plugin: string, method: string, options: object) => Promise<{ shown?: boolean }>;
};

/** The native app's « Ouvrir dans… » (null in a browser or the home-screen web app). */
export function nativeOpenIn(): ((filename: string, data64: string) => Promise<{ shown?: boolean }>) | null {
  const cap = (window as Window & { Capacitor?: CapacitorGlobal }).Capacitor;
  if (!cap?.isNativePlatform?.() || !cap.nativePromise) return null;
  return (filename, data) => cap.nativePromise!("OpenIn", "open", { filename, data });
}

function toBase64(data: ArrayBuffer): string {
  const bytes = new Uint8Array(data);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** In the native app: « Ouvrir dans… » on the prepared GPX. */
export function openInNative(gpx: PreparedGpx, filename: string): Promise<{ shown?: boolean }> | "not-ready" {
  const open = nativeOpenIn();
  if (!open || !gpx.data64) return "not-ready";
  debugLog("app native : Ouvrir dans…", filename);
  return open(filename, gpx.data64);
}

/** The fallback: the signed link in a new window (iOS home-screen app: over the app, out of its scope). */
export function openLink(gpx: PreparedGpx): boolean {
  if (gpx.link && gpx.expires - Date.now() / 1000 < 60) {
    gpx.link = null; // about to expire (the route stayed on screen for an hour): a new one for the next tap
    fetchLink(gpx).catch((e) => debugLog("lien", String(e)));
  }
  if (!gpx.link) return false;
  debugLog("repli /dl", gpx.link.split("?")[0]);
  window.open(gpx.link, "_blank");
  return true;
}
