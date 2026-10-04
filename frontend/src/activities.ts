import { LngLatBounds, Popup } from "maplibre-gl";
import type { IControl, Map, MapLayerMouseEvent } from "maplibre-gl";
import type { ActivityCollection, ActivityFeature, FrequencyCollection, Sport } from "./api";
import { duration, escape, formatDate, km } from "./format";

export const SPORTS: Record<Sport, { label: string; color: string }> = {
  run: { label: "Course", color: "#e4572e" },
  trail_run: { label: "Trail", color: "#7b2cbf" },
  hike: { label: "Randonnée", color: "#2a9d8f" },
};

const SOURCE = "activities";
const FREQ = "activities-frequency";
const MODE_KEY = "trailmap.tracksMode";

type TracksMode = "frequency" | "sport";

/** Pass levels (lower bounds, as served by /api/frequency): light and thin -> dark and thick. */
const FREQ_STYLE: { from: number; color: string; width: number }[] = [
  { from: 1, color: "#fdb863", width: 1.6 },
  { from: 2, color: "#f98e3c", width: 2.1 },
  { from: 3, color: "#ec6224", width: 2.6 },
  { from: 5, color: "#cf3a17", width: 3.2 },
  { from: 10, color: "#a51d10", width: 3.9 },
  { from: 20, color: "#730d0b", width: 4.7 },
  { from: 50, color: "#430707", width: 5.6 },
];

function stepBy<T>(prop: (s: (typeof FREQ_STYLE)[number]) => T) {
  return ["step", ["get", "passes"], prop(FREQ_STYLE[0]), ...FREQ_STYLE.slice(1).flatMap((s) => [s.from, prop(s)])];
}

/** The user's tracks layer and the "Mes sorties" tab. */
export class ActivitiesView {
  private enabled = new Set<Sport>(Object.keys(SPORTS) as Sport[]);
  private hovered: number | null = null;
  private selected: number | null = null;
  private popup: Popup | null = null;
  private mode: TracksMode;
  private muted = false;
  private visibleLayers = true;
  private legend: FrequencyLegend | null = null;
  interactive = false; // only clickable while the "Mes sorties" tab is open

  constructor(
    private map: Map,
    private fc: ActivityCollection,
    private onSummary: (text: string) => void,
    freq: FrequencyCollection | null = null,
  ) {
    this.mode = freq ? loadMode() : "sport";
    // The frequency layer is drawn under the per-activity one, which stays (transparent) on top
    // in frequency mode: hover, click and the activity sheet work the same in both modes.
    if (freq) {
      map.addSource(FREQ, { type: "geojson", data: freq as never });
      map.addLayer({
        id: FREQ,
        type: "line",
        source: FREQ,
        layout: { "line-join": "round", "line-cap": "round", "line-sort-key": ["get", "passes"] },
        paint: {
          "line-color": stepBy((s) => s.color) as never,
          // Thinner when zoomed out, so busy areas stay readable.
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["*", 0.6, stepBy((s) => s.width)], 16, ["*", 1.4, stepBy((s) => s.width)]] as never,
        },
      });
      this.legend = new FrequencyLegend(freq.max_passes);
      map.addControl(this.legend, "top-right");
    }
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
    // Frequency pieces are wider than the hidden activity lines: they answer the pointer too.
    for (const layer of freq ? [SOURCE, FREQ] : [SOURCE]) {
      map.on("mousemove", layer, (e: MapLayerMouseEvent) => {
        if (!this.interactive) return;
        map.getCanvas().style.cursor = "pointer";
        const id = activityId(e);
        if (id !== undefined && id !== this.hovered) this.setHover(id);
      });
      map.on("mouseleave", layer, () => {
        if (!this.interactive) return;
        map.getCanvas().style.cursor = "";
        this.setHover(null);
      });
      map.on("click", layer, (e: MapLayerMouseEvent) => {
        const id = activityId(e);
        if (this.interactive && id !== undefined && this.selected !== id) this.select(fc.features[id], e.lngLat.toArray() as [number, number]);
      });
    }
    this.renderMode();
    this.applyStyle();
    this.renderFilters();
    this.renderList();
    onSummary(this.summary());
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

  /** Layer visibility and opacity for the current mode, muting and visibility. */
  private applyStyle() {
    const { map } = this;
    const freq = this.mode === "frequency";
    const rest = freq ? 0 : this.muted ? 0.15 : 0.55; // non-highlighted activity lines
    map.setPaintProperty(SOURCE, "line-opacity", ["case", ["boolean", ["feature-state", "highlight"], false], 1, rest]);
    map.setLayoutProperty(SOURCE, "visibility", this.visibleLayers ? "visible" : "none");
    if (map.getLayer(FREQ)) {
      map.setPaintProperty(FREQ, "line-opacity", this.muted ? 0.2 : 1);
      map.setLayoutProperty(FREQ, "visibility", this.visibleLayers && freq ? "visible" : "none");
    }
    this.legend?.setVisible(this.visibleLayers && freq);
  }

  private renderMode() {
    const box = document.getElementById("tracks-mode")!;
    box.parentElement!.hidden = !this.map.getLayer(FREQ); // no frequency data: by sport only
    box.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === this.mode);
      b.onclick = () => {
        this.mode = b.dataset.mode as TracksMode;
        saveMode(this.mode);
        this.renderMode();
        this.applyStyle();
      };
    });
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
    const popup = new Popup({ maxWidth: "260px" })
      .setLngLat(at ?? f.geometry.coordinates[0][0])
      .setHTML(
        `<strong>${escape(p.name ?? "Sans nom")}</strong><br>` +
          `${formatDate(p.start)} · ${p.sport ? SPORTS[p.sport]?.label ?? p.sport : "?"}<br>` +
          `${km(p.distance_m)} · D+ ${p.ascent_m} m${p.duration_s ? ` · ${duration(p.duration_s)}` : ""}`,
      )
      .addTo(map);
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
        this.map.setFilter(SOURCE, ["in", ["get", "sport"], ["literal", [...this.enabled]]]);
        // Each path is drawn once for all sports: shown when any enabled sport went there.
        if (this.map.getLayer(FREQ)) this.map.setFilter(FREQ, ["any", ...[...this.enabled].map((s) => ["==", ["get", s], true])] as never);
        this.renderList();
        this.onSummary(this.summary());
      });
      box.appendChild(label);
    });
  }

  private renderList() {
    const list = document.getElementById("list")!;
    list.innerHTML = "";
    this.visible()
      .slice()
      .reverse()
      .forEach((f) => {
        const p = f.properties;
        const li = document.createElement("li");
        li.dataset.id = String(f.id);
        li.style.setProperty("--c", p.sport ? SPORTS[p.sport]?.color ?? "#888" : "#888");
        li.innerHTML =
          `<span class="name">${escape(p.name ?? "Sans nom")}</span>` +
          `<span class="meta">${formatDate(p.start)} · ${km(p.distance_m)} · D+ ${p.ascent_m} m</span>`;
        li.addEventListener("mouseenter", () => this.setHover(f.id));
        li.addEventListener("mouseleave", () => this.setHover(null));
        li.addEventListener("click", () => {
          fitTo(this.map, [f]);
          this.select(f);
        });
        list.appendChild(li);
      });
  }

  private visible() {
    return this.fc.features.filter((f) => f.properties.sport && this.enabled.has(f.properties.sport));
  }

  private summary() {
    const shown = this.visible();
    const total = shown.reduce((s, f) => s + f.properties.distance_m, 0);
    const dplus = shown.reduce((s, f) => s + f.properties.ascent_m, 0);
    return `${shown.length} sorties · ${Math.round(total / 1000).toLocaleString("fr-FR")} km · D+ ${dplus.toLocaleString("fr-FR")} m`;
  }
}

/** Pass-count legend, as a map control so it stays clear of the side / bottom panel. */
class FrequencyLegend implements IControl {
  private el = document.createElement("div");

  constructor(maxPasses: number) {
    this.el.className = "maplibregl-ctrl maplibregl-ctrl-group freq-legend";
    const shown = FREQ_STYLE.filter((s) => s.from <= Math.max(maxPasses, 1));
    this.el.innerHTML =
      `<strong>Passages</strong>` +
      shown
        .map((s, i) => {
          const next = shown[i + 1]?.from;
          const label = next === undefined ? (s.from === maxPasses ? `${s.from}` : `${s.from}+`) : next - s.from === 1 ? `${s.from}` : `${s.from}–${next - 1}`;
          return `<div class="row"><span class="swatch" style="--c:${s.color};height:${Math.max(2, Math.round(s.width))}px"></span>${label}</div>`;
        })
        .join("");
    this.el.title = "Nombre de sorties distinctes passées par ce chemin (un aller-retour compte une fois)";
  }

  onAdd() {
    return this.el;
  }

  onRemove() {
    this.el.remove();
  }

  setVisible(visible: boolean) {
    this.el.hidden = !visible;
  }
}

function activityId(e: MapLayerMouseEvent): number | undefined {
  const f = e.features?.[0];
  return (f?.layer.id === FREQ ? f.properties?.activity : f?.id) as number | undefined;
}

function loadMode(): TracksMode {
  try {
    return localStorage.getItem(MODE_KEY) === "sport" ? "sport" : "frequency";
  } catch {
    return "frequency";
  }
}

function saveMode(mode: TracksMode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* storage unavailable: the mode just won't persist */
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
