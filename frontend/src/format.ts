export const km = (m: number) => `${(m / 1000).toFixed(1).replace(".", ",")} km`;

export const pct = (x: number) => `${Math.round(x * 100)} %`;

export function duration(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
}

export function formatDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" }) : "?";
}

export function escape(s: string) {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export const GPX_TYPE = "application/gpx+xml";

/** Phone or tablet: the share sheet is the way to hand a file to another app (COROS). */
export const isMobile = () => matchMedia("(pointer: coarse)").matches;

/**
 * Opens the system share sheet with only the file: adding a title or text makes iOS share
 * text as well, and then hides the apps that only accept a GPX file (COROS).
 * Must be called synchronously from the click, or Safari refuses it (no user activation).
 * Resolves false when sharing a file isn't possible here; a cancel (AbortError) resolves true.
 */
export async function shareFile(file: File): Promise<boolean> {
  if (!navigator.canShare?.({ files: [file] })) return false;
  try {
    await navigator.share({ files: [file] });
  } catch (e) {
    if ((e as DOMException).name !== "AbortError") throw e;
  }
  return true;
}
