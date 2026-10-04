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

export function toGpx(name: string, coords: number[][]) {
  const pts = coords
    .map(([lon, lat, ele]) => (ele === undefined ? `<trkpt lat="${lat}" lon="${lon}"/>` : `<trkpt lat="${lat}" lon="${lon}"><ele>${ele}</ele></trkpt>`))
    .join("\n      ");
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Trail Map" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>${escape(name)}</name>
    <trkseg>
      ${pts}
    </trkseg>
  </trk>
</gpx>
`;
}

export function download(filename: string, content: string, type = "application/gpx+xml") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** A GPX file the system share sheet accepts (to open it in the COROS app), or null when unsupported. */
export function shareableGpx(filename: string, content: string): File | null {
  const file = new File([content], filename, { type: "application/gpx+xml" });
  return navigator.canShare?.({ files: [file] }) ? file : null;
}

/** Opens the system share sheet; resolves false when the user cancels. */
export async function shareFile(file: File, title: string): Promise<boolean> {
  try {
    await navigator.share({ files: [file], title });
    return true;
  } catch (e) {
    if ((e as DOMException).name === "AbortError") return false;
    throw e;
  }
}
