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

/** Phone or tablet: where the « Envoyer vers la montre » button makes sense (COROS app on the phone). */
export const isMobile = () => matchMedia("(pointer: coarse)").matches;
