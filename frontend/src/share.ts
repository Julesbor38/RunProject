/**
 * Getting a route's GPX on a phone without ever leaving or replacing the app's page (in the app added to the
 * iOS home screen, a download replaces it with a full-screen file preview that has no way back).
 *
 * 1. The system share sheet, over the app: the File is built in advance (as soon as the route is shown), so
 *    that the tap calls navigator.share synchronously (Safari refuses it once the tap's activation is lost).
 * 0. In the native iOS app (Capacitor, ios/): the GPX is written into the app's storage, then shared from the
 *    native share sheet (Filesystem + Share plugins): a real file, never shown in place of the app.
 * 2. Fallback, when files can't be shared: a signed /dl/ link, outside the PWA scope (/app/), opened in a new
 *    window: iOS shows it over the app with its own « OK », never in place of the app.
 */
import { Directory, Encoding, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { apiFetch, gpxUrl } from "./api";
import { isNative } from "./native";
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
  text: string | null; // the GPX itself, for the native app
  link: string | null; // signed /dl/ link (fallback)
  expires: number; // of the link (epoch s)
  failed: string | null;
  routeId: string;
}

/** Fetch the route's GPX and its signed link right away, so that a later tap needs no await. */
export function prepareGpx(routeId: string, filename: string): PreparedGpx {
  const out: PreparedGpx = { ready: false, file: null, text: null, link: null, expires: 0, failed: null, routeId };
  const file = apiFetch(gpxUrl(routeId))
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`GPX : erreur ${r.status}`))))
    .then((data) => {
      if (isNative()) out.text = new TextDecoder().decode(data);
      const { file: f, checks } = shareableFile(data, filename);
      setGpxChecks(filename, checks, f?.type ?? null);
      out.file = f;
    });
  const link = isNative() ? Promise.resolve() : fetchLink(out); // the native app shares the file itself
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

/**
 * Native app: write the GPX into the app's cache, then the system share sheet on that file. Resolves
 * "shared" or "cancelled" (the user closed the sheet: nothing to say), rejects on a real error.
 */
export async function shareNative(gpx: PreparedGpx, filename: string): Promise<"shared" | "cancelled" | "not-ready"> {
  if (gpx.text === null) return "not-ready";
  const { uri } = await Filesystem.writeFile({ path: filename, data: gpx.text, directory: Directory.Cache, encoding: Encoding.UTF8 });
  debugLog("app : partage", `${filename} (${uri.split("/").slice(-2).join("/")})`);
  try {
    await Share.share({ files: [uri] });
    return "shared";
  } catch (e) {
    if (/cancel/i.test(String((e as Error).message))) return "cancelled";
    throw e;
  }
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
