import { LngLatBounds, Popup } from "maplibre-gl";
import type { Map, MapLayerMouseEvent, PointLike } from "maplibre-gl";
import type { ActivityCollection, ActivityFeature, Sport } from "./api";
import { duration, escape, formatDate, km } from "./format";
import { forgetNewActivities } from "./importer";
import type { Ratings } from "./ratings";

export const SPORTS: Record<Sport, { label: string; color: string }> = {
  run: { label: "Course", color: "#e4572e" },
  trail_run: { label: "Trail", color: "#7b2cbf" },
  hike: { label: "Randonnée", color: "#2a9d8f" },
};

const SOURCE = "activities";
const HIT = "activities-hit"; // invisible wide lines: thin tracks are easy to tap, even with a finger
/** The user's tracks layer and the "Mes sorties" tab. */
export class ActivitiesView {
  private enabled = new Set<Sport>(Object.keys(SPORTS) as Sport[]);
  private hovered: number | null = null;
  private selected: number | null = null;
  private popup: Popup | null = null;
  private muted = false;
  private visibleLayers = true;
  /** Whether a click / hover at this point is for the tracks (set by main.ts: not while the planner uses it). */
  clickable: (point: PointLike) => boolean = () => true;

  constructor(
    private map: Map,
    private fc: ActivityCollection,
    private onSummary: (text: string) => void,
    private ratings: Ratings,
    private newKeys: Set<string>, // added by the last import: put forward, to be rated
  ) {
    map.addSource(SOURCE, { type: "geojson", data: fc as never });
    map.addLayer({
      id: SOURCE,
      type: "line",
      source: SOURCE,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": ["match", ["get", "sport"], ...Object.entries(SPORTS).flatMap(([k, v]) => [k, v.color]), "#888"] as never,
        "line-width": ["case", ["boolean", ["feature-state", "highlight"], false], 5, 2.5],
      },
    });
    map.addLayer({
      id: HIT,
      type: "line",
      source: SOURCE,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#000", "line-opacity": 0, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 10, 15, 20] },
    });
    map.on("mousemove", HIT, (e: MapLayerMouseEvent) => {
      if (!this.clickable(e.point)) return this.leave();
      map.getCanvas().style.cursor = "pointer";
      const id = e.features?.[0]?.id as number | undefined;
      if (id !== undefined && id !== this.hovered) this.setHover(id);
    });
    map.on("mouseleave", HIT, () => this.leave());
    map.on("click", HIT, (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.id as number | undefined;
      if (id !== undefined && this.selected !== id && this.clickable(e.point)) this.select(fc.features[id], e.lngLat.toArray() as [number, number]);
    });
    this.applyStyle();
    this.renderFilters();
    this.renderList();
    this.renderNewBanner();
    onSummary(this.summary());
    ratings.onChange(() => {
      this.renderList();
      this.renderNewBanner();
    });
  }

  /** Dim tracks behind generated routes. */
  setMuted(muted: boolean) {
    this.muted = muted;
    this.applyStyle();
  }

  setVisible(visible: boolean) {
    this.visibleLayers = visible;
    this.applyStyle();
  }

  private leave() {
    if (this.hovered === null) return;
    this.map.getCanvas().style.cursor = "";
    this.setHover(null);
  }

  /** Opacity (dimmed behind routes) and visibility of the tracks. */
  private applyStyle() {
    const { map } = this;
    const rest = this.muted ? 0.15 : 0.55; // non-highlighted tracks
    map.setPaintProperty(SOURCE, "line-opacity", ["case", ["boolean", ["feature-state", "highlight"], false], 1, rest]);
    for (const layer of [SOURCE, HIT]) map.setLayoutProperty(layer, "visibility", this.visibleLayers ? "visible" : "none");
  }

  /** Center of the ~5 km cell holding the most activity starts: the user's home area. */
  homeCenter(): [number, number] | null {
    const cells = new globalThis.Map<string, { n: number; lon: number; lat: number }>();
    for (const f of this.fc.features) {
      const first = f.geometry.coordinates[0]?.[0];
      if (!first) continue;
      const key = `${Math.round(first[0] / 0.05)},${Math.round(first[1] / 0.05)}`;
      const c = cells.get(key) ?? { n: 0, lon: 0, lat: 0 };
      c.n += 1;
      c.lon += first[0];
      c.lat += first[1];
      cells.set(key, c);
    }
    let best: { n: number; lon: number; lat: number } | null = null;
    for (const c of cells.values()) if (!best || c.n > best.n) best = c;
    return best ? [best.lon / best.n, best.lat / best.n] : null;
  }

  private setHover(id: number | null) {
    const { map } = this;
    if (this.hovered !== null && this.hovered !== this.selected) map.setFeatureState({ source: SOURCE, id: this.hovered }, { highlight: false });
    this.hovered = id;
    if (id !== null) map.setFeatureState({ source: SOURCE, id }, { highlight: true });
    document.querySelectorAll("#list li").forEach((li) => li.classList.toggle("hover", Number((li as HTMLElement).dataset.id) === id));
  }

  private select(f: ActivityFeature, at?: [number, number]) {
    const { map } = this;
    if (this.selected !== null) map.setFeatureState({ source: SOURCE, id: this.selected }, { highlight: false });
    this.popup?.remove();
    this.selected = f.id;
    map.setFeatureState({ source: SOURCE, id: f.id }, { highlight: true });
    const p = f.properties;
    const avg = this.ratings.average(p.key);
    const popup = new Popup({ maxWidth: "260px" })
      .setLngLat(at ?? f.geometry.coordinates[0][0])
      .setHTML(
        `<strong>${escape(p.name ?? "Sans nom")}</strong><br>` +
          `${formatDate(p.start)} · ${p.sport ? SPORTS[p.sport]?.label ?? p.sport : "?"}<br>` +
          `${km(p.distance_m)} · D+ ${p.ascent_m} m${p.duration_s ? ` · ${duration(p.duration_s)}` : ""}` +
          `<br><button class="action rate-btn">${avg === null ? "Évaluer cette sortie" : `★ ${avg.toFixed(1).replace(".", ",")} · Modifier`}</button>`,
      )
      .addTo(map);
    popup.getElement().querySelector(".rate-btn")!.addEventListener("click", () => this.ratings.open(f));
    popup.on("close", () => {
      if (this.selected === f.id) {
        map.setFeatureState({ source: SOURCE, id: f.id }, { highlight: false });
        this.selected = null;
      }
    });
    this.popup = popup;
    document.querySelectorAll("#list li").forEach((li) => li.classList.toggle("selected", Number((li as HTMLElement).dataset.id) === f.id));
  }

  private renderFilters() {
    const counts = new globalThis.Map<Sport, number>();
    this.fc.features.forEach((f) => f.properties.sport && counts.set(f.properties.sport, (counts.get(f.properties.sport) ?? 0) + 1));
    const box = document.getElementById("filters")!;
    box.innerHTML = "";
    (Object.keys(SPORTS) as Sport[]).forEach((sport) => {
      const label = document.createElement("label");
      label.className = "chip";
      label.style.setProperty("--c", SPORTS[sport].color);
      label.innerHTML = `<input type="checkbox" checked> <span class="dot"></span>${SPORTS[sport].label} <small>${counts.get(sport) ?? 0}</small>`;
      label.querySelector("input")!.addEventListener("change", (e) => {
        (e.target as HTMLInputElement).checked ? this.enabled.add(sport) : this.enabled.delete(sport);
        for (const layer of [SOURCE, HIT]) this.map.setFilter(layer, ["in", ["get", "sport"], ["literal", [...this.enabled]]]);
        this.renderList();
        this.onSummary(this.summary());
      });
      box.appendChild(label);
    });
  }

  private renderList() {
    const list = document.getElementById("list")!;
    list.innerHTML = "";
    if (!this.fc.features.length) {
      list.innerHTML = `<li class="empty">Aucune sortie pour l'instant. Ajoutez votre archive Strava (.zip) ou les fichiers
        de votre montre (.fit, .gpx) avec « Mettre à jour mes données » ci-dessus : vos sorties apparaîtront ici et sur la carte.</li>`;
      return;
    }
    this.visible()
      .slice()
      .reverse()
      .forEach((f) => {
        const p = f.properties;
        const li = document.createElement("li");
        li.dataset.id = String(f.id);
        li.style.setProperty("--c", p.sport ? SPORTS[p.sport]?.color ?? "#888" : "#888");
        const avg = this.ratings.average(p.key);
        li.classList.toggle("new", this.newKeys.has(p.key));
        li.innerHTML =
          `<span class="name">${escape(p.name ?? "Sans nom")}${this.newKeys.has(p.key) ? ` <span class="tag">Nouveau</span>` : ""}</span>` +
          `<span class="meta">${formatDate(p.start)} · ${km(p.distance_m)} · D+ ${p.ascent_m} m</span>` +
          (avg === null
            ? `<button class="rate-chip" title="Évaluer : sécurité, éclairage, paysage…">Évaluer</button>`
            : `<button class="rate-chip rated" title="Modifier l'évaluation">★ ${avg.toFixed(1).replace(".", ",")}</button>`);
        li.querySelector(".rate-chip")!.addEventListener("click", (e) => {
          e.stopPropagation();
          this.ratings.open(f);
        });
        li.addEventListener("mouseenter", () => this.setHover(f.id));
        li.addEventListener("mouseleave", () => this.setHover(null));
        li.addEventListener("click", () => {
          fitTo(this.map, [f]);
          this.select(f);
        });
        list.appendChild(li);
      });
  }

  /** After an import: how many new activities are left to rate, and a button to rate the next one. */
  private renderNewBanner() {
    const box = document.getElementById("new-banner")!;
    const unrated = this.fc.features.filter((f) => this.newKeys.has(f.properties.key) && this.ratings.average(f.properties.key) === null);
    box.hidden = !this.newKeys.size;
    if (!this.newKeys.size) return;
    const n = this.newKeys.size;
    box.innerHTML = unrated.length
      ? `<span><strong>${n} nouvelle${n > 1 ? "s" : ""} sortie${n > 1 ? "s" : ""}</strong> : ${unrated.length} à évaluer.</span>
         <button class="action watch next">Évaluer</button><button class="icon-btn dismiss" aria-label="Fermer">×</button>`
      : `<span>Toutes les nouvelles sorties sont évaluées, merci !</span><button class="icon-btn dismiss" aria-label="Fermer">×</button>`;
    box.querySelector(".next")?.addEventListener("click", () => {
      const f = unrated[unrated.length - 1]; // oldest first
      fitTo(this.map, [f]);
      this.select(f);
      this.ratings.open(f);
    });
    box.querySelector(".dismiss")!.addEventListener("click", () => {
      this.newKeys.clear();
      forgetNewActivities();
      this.renderNewBanner();
      this.renderList();
    });
  }

  private visible() {
    return this.fc.features.filter((f) => f.properties.sport && this.enabled.has(f.properties.sport));
  }

  private summary() {
    const shown = this.visible();
    const total = shown.reduce((s, f) => s + f.properties.distance_m, 0);
    const dplus = shown.reduce((s, f) => s + f.properties.ascent_m, 0);
    return `${shown.length} sortie${shown.length > 1 ? "s" : ""} · ${Math.round(total / 1000).toLocaleString("fr-FR")} km · D+ ${dplus.toLocaleString("fr-FR")} m`;
  }
}

export function fitTo(map: Map, features: { geometry: { coordinates: unknown } }[], padding = 40) {
  const b = new LngLatBounds();
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number]);
    else if (Array.isArray(c)) c.forEach(visit);
  };
  features.forEach((f) => visit(f.geometry.coordinates));
  if (!b.isEmpty()) map.fitBounds(b, { padding, maxZoom: 15, duration: 600 });
}
