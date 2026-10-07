/**
 * « Exploration » tab (like Zenly / Wandrer): my communes with the share of their paths I have run, places
 * discovered, milestones and badges, suggestions of paths never run nearby; on the map, the « Brouillard »:
 * the paths I ran lit up, the others greyed, the selected commune's boundary. Only the visible area is loaded.
 */
import type { GeoJSONSource, Map } from "maplibre-gl";
import { apiFetch } from "./api";
import type { LngLat } from "./api";
import { escape, formatDate } from "./format";

interface Town {
  id: string;
  name: string;
  pct: number | null;
  done_m: number;
  total_m: number | null;
  pois: number;
  last: string | null;
}

interface Achievement {
  id: string;
  kind: "milestone" | "badge";
  badge?: string;
  title: string;
  detail: string;
  achieved: boolean;
  progress?: number;
  goal?: number;
}

interface Summary {
  status: { state: string; done?: number; total?: number };
  totals: { done_m: number; segments: number; activities: number };
  communes: Town[];
  achievements: Achievement[];
  new: Achievement[];
  discovered: number;
  suggestions: { lat: number; lon: number; new_km: number; total_km: number; distance_km: number }[];
  suggestions_pending: boolean;
}

const FOG = "explore-fog";
const VEIL = "explore-veil";
const TOWN = "explore-town";
const BADGE_ICONS: Record<string, string> = {
  communes: "i-town", peaks: "i-peak", waterfalls: "i-drop", viewpoints: "i-eye", heritage: "i-castle", lakes: "i-waves",
};
const MIN_FOG_ZOOM = 13;

export class ExploreView {
  private fogOn = false;
  private timer = 0;
  private abort: AbortController | null = null;
  private poll = 0;
  private townId: string | null = null;

  constructor(
    private map: Map,
    private onDiscover: (at: LngLat) => void,
    private setTracksVisible: (visible: boolean) => void,
  ) {
    map.addSource(FOG, { type: "geojson", data: empty() });
    map.addSource(TOWN, { type: "geojson", data: empty() });
    // Under the routes and the places (and the tracks, hidden in fog mode): first of ours, "activities".
    const before = map.getLayer("activities") ? "activities" : undefined;
    // A veil over the base map, under the paths: the unexplored world fades away.
    map.addLayer({ id: VEIL, type: "background", layout: { visibility: "none" }, paint: { "background-color": "#1d2622", "background-opacity": 0.45 } }, before);
    map.addLayer({
      id: `${FOG}-todo`,
      type: "line",
      source: FOG,
      filter: ["!", ["get", "done"]],
      layout: { visibility: "none", "line-cap": "round" },
      paint: { "line-color": "#9aa59f", "line-width": ["interpolate", ["linear"], ["zoom"], 13, 1, 17, 3], "line-opacity": 0.75 },
    }, before);
    map.addLayer({
      id: `${FOG}-done`,
      type: "line",
      source: FOG,
      filter: ["get", "done"],
      layout: { visibility: "none", "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffcf4d", "line-width": ["interpolate", ["linear"], ["zoom"], 13, 2.5, 17, 6], "line-blur": 0.5 },
    }, before);
    map.addLayer({
      id: TOWN,
      type: "line",
      source: TOWN,
      paint: { "line-color": "#ffffff", "line-width": 2.5, "line-dasharray": [2, 1.5], "line-opacity": 0.9 },
    }, before);
    map.on("moveend", () => this.fogOn && this.scheduleFog());
    document.getElementById("fog-toggle")!.addEventListener("change", (e) => this.setFog((e.target as HTMLInputElement).checked));
  }

  /** Called when the tab opens: the summary (and the milestones just crossed). */
  async refresh() {
    clearTimeout(this.poll);
    const r = await apiFetch("/api/explore");
    if (!r.ok) return;
    const s = (await r.json()) as Summary;
    this.render(s);
    if (s.status.state === "running" || s.suggestions_pending) this.poll = window.setTimeout(() => this.refresh(), 3000);
    else if (s.new.length) this.celebrate(s.new);
  }

  private render(s: Summary) {
    const status = document.getElementById("explore-status")!;
    status.hidden = s.status.state !== "running";
    status.textContent = `Mise à jour de l'exploration : ${s.status.done ?? 0}/${s.status.total ?? "…"} sorties…`;
    const km = (m: number) => (m / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
    document.getElementById("explore-totals")!.innerHTML = `
      <div><strong>${km(s.totals.done_m)}</strong><span>km de chemins découverts</span></div>
      <div><strong>${s.communes.length}</strong><span>commune${s.communes.length > 1 ? "s" : ""}</span></div>
      <div><strong>${s.discovered}</strong><span>lieu${s.discovered > 1 ? "x" : ""} découvert${s.discovered > 1 ? "s" : ""}</span></div>`;

    const sugg = document.getElementById("explore-suggestions")!;
    sugg.innerHTML = s.suggestions
      .map(
        (x, i) => `<div class="suggestion"><span><strong>${km(x.new_km * 1000)} km</strong> de chemins jamais courus à ${km(x.distance_km * 1000)} km d'ici</span>
          <button type="button" class="action watch" data-i="${i}">Explorer</button></div>`,
      )
      .join("");
    sugg.querySelectorAll<HTMLButtonElement>("button").forEach((b) =>
      b.addEventListener("click", () => {
        const x = s.suggestions[Number(b.dataset.i)];
        this.onDiscover([x.lon, x.lat]);
      }),
    );

    const list = document.getElementById("explore-towns")!;
    list.innerHTML = s.communes.length
      ? s.communes
          .map(
            (t) => `<li data-id="${escape(t.id)}" class="${t.id === this.townId ? "selected" : ""}">
            ${ring(t.pct)}
            <div><span class="name">${escape(t.name)}</span>
            <span class="meta">${km(t.done_m)}${t.total_m ? ` / ${km(t.total_m)}` : ""} km · ${t.pois} lieu${t.pois > 1 ? "x" : ""}${t.last ? ` · ${formatDate(t.last)}` : ""}</span></div></li>`,
          )
          .join("")
      : `<li class="empty">Rien encore : la carte se remplit avec vos sorties (horodatées) dès qu'elles sont analysées.</li>`;
    list.querySelectorAll<HTMLLIElement>("li[data-id]").forEach((li) => li.addEventListener("click", () => this.selectTown(li.dataset.id!)));

    const badges = s.achievements.filter((a) => a.kind === "badge");
    // per badge family: the highest achieved and the next one to reach
    const families = new globalThis.Map<string, Achievement[]>();
    badges.forEach((a) => families.set(a.badge!, [...(families.get(a.badge!) ?? []), a]));
    document.getElementById("explore-badges")!.innerHTML = [...families]
      .map(([name, steps]) => {
        const got = steps.filter((a) => a.achieved).pop();
        const next = steps.find((a) => !a.achieved);
        const shown = got ?? next!;
        const sub = !got ? `${next!.progress}/${next!.goal}` : next ? `prochain : ${next.goal} (${next.progress}/${next.goal})` : "tous obtenus";
        return `<div class="badge-card ${got ? "on" : ""}" title="${escape(shown.detail)}">
          <svg class="i badge-icon"><use href="#${BADGE_ICONS[name] ?? "i-peak"}"/></svg><strong>${escape(shown.title)}</strong>
          <span class="muted small">${sub}</span></div>`;
      })
      .join("");
  }

  /** A short, quiet celebration of the milestones and badges crossed since last time (then not again). */
  private celebrate(news: Achievement[]) {
    const box = document.getElementById("achievement-toast")!;
    const shown = news.slice(0, 3);
    box.innerHTML = `<span class="spark">✦</span><div><strong>${news.length > 1 ? "Nouveaux paliers" : "Nouveau palier"}</strong>
      ${shown.map((a) => `<span>${escape(a.title)}</span>`).join("")}${news.length > 3 ? `<span class="muted">et ${news.length - 3} autre(s)</span>` : ""}</div>`;
    box.hidden = false;
    box.classList.remove("show");
    void box.offsetWidth; // restart the animation
    box.classList.add("show");
    setTimeout(() => (box.hidden = true), 5200);
    apiFetch("/api/explore/seen", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids: news.map((a) => a.id) }),
    }).catch(() => {});
  }

  private async selectTown(id: string) {
    this.townId = id;
    document.querySelectorAll("#explore-towns li").forEach((li) => li.classList.toggle("selected", (li as HTMLElement).dataset.id === id));
    const r = await apiFetch(`/api/explore/communes/${encodeURIComponent(id)}`);
    if (!r.ok) return;
    const town = await r.json();
    (this.map.getSource(TOWN) as GeoJSONSource).setData(town);
    const [w, s, e, n] = town.bbox;
    this.map.fitBounds([[w, s], [e, n]], { padding: 30, maxZoom: 15, duration: 700 });
    if (!this.fogOn) {
      (document.getElementById("fog-toggle") as HTMLInputElement).checked = true;
      this.setFog(true);
    }
  }

  setFog(on: boolean) {
    this.fogOn = on;
    for (const id of [VEIL, `${FOG}-todo`, `${FOG}-done`]) this.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    this.setTracksVisible(!on);
    if (on) this.scheduleFog(0);
    else document.getElementById("fog-hint")!.hidden = true;
  }

  private scheduleFog(delay = 300) {
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.loadFog(), delay);
  }

  private async loadFog() {
    const hint = document.getElementById("fog-hint")!;
    const source = this.map.getSource(FOG) as GeoJSONSource;
    if (this.map.getZoom() < MIN_FOG_ZOOM) {
      hint.hidden = false;
      return source.setData(empty());
    }
    hint.hidden = true;
    const b = this.map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(4)).join(",");
    this.abort?.abort();
    const abort = (this.abort = new AbortController());
    try {
      const r = await apiFetch(`/api/explore/fog?bbox=${bbox}`, { signal: abort.signal });
      if (r.ok && !abort.signal.aborted) source.setData(await r.json());
    } catch {
      /* a newer move took over */
    }
  }
}

function empty() {
  return { type: "FeatureCollection" as const, features: [] };
}

/** Progress ring (SVG) with the percentage in the middle. */
function ring(pct: number | null): string {
  const r = 17;
  const c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, pct ?? 0));
  return `<svg class="ring" viewBox="0 0 44 44" aria-label="${pct === null ? "en calcul" : `${p} %`}">
    <circle cx="22" cy="22" r="${r}" class="ring-bg"/>
    <circle cx="22" cy="22" r="${r}" class="ring-fg" stroke-dasharray="${((p / 100) * c).toFixed(1)} ${c.toFixed(1)}"/>
    <text x="22" y="26" text-anchor="middle">${pct === null ? "…" : p < 10 ? p.toFixed(1).replace(".", ",") : Math.round(p)}</text></svg>`;
}
