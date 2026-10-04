import { LngLatBounds, Popup } from "maplibre-gl";
import type { Map, MapLayerMouseEvent } from "maplibre-gl";
import type { ActivityCollection, ActivityFeature, Sport } from "./api";
import { duration, escape, formatDate, km } from "./format";

export const SPORTS: Record<Sport, { label: string; color: string }> = {
  run: { label: "Course", color: "#e4572e" },
  trail_run: { label: "Trail", color: "#7b2cbf" },
  hike: { label: "Randonnée", color: "#2a9d8f" },
};

const SOURCE = "activities";

/** The user's tracks layer and the "Mes sorties" tab. */
export class ActivitiesView {
  private enabled = new Set<Sport>(Object.keys(SPORTS) as Sport[]);
  private hovered: number | null = null;
  private selected: number | null = null;
  private popup: Popup | null = null;
  interactive = false; // only clickable while the "Mes sorties" tab is open

  constructor(
    private map: Map,
    private fc: ActivityCollection,
    private onSummary: (text: string) => void,
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
        "line-opacity": ["case", ["boolean", ["feature-state", "highlight"], false], 1, 0.55],
      },
    });
    map.on("mousemove", SOURCE, (e: MapLayerMouseEvent) => {
      if (!this.interactive) return;
      map.getCanvas().style.cursor = "pointer";
      const id = e.features?.[0]?.id as number | undefined;
      if (id !== undefined && id !== this.hovered) this.setHover(id);
    });
    map.on("mouseleave", SOURCE, () => {
      if (!this.interactive) return;
      map.getCanvas().style.cursor = "";
      this.setHover(null);
    });
    map.on("click", SOURCE, (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.id as number | undefined;
      if (this.interactive && id !== undefined) this.select(fc.features[id], e.lngLat.toArray() as [number, number]);
    });
    this.renderFilters();
    this.renderList();
    onSummary(this.summary());
  }

  /** Dim tracks behind generated routes. */
  setMuted(muted: boolean) {
    this.map.setPaintProperty(SOURCE, "line-opacity", [
      "case",
      ["boolean", ["feature-state", "highlight"], false],
      1,
      muted ? 0.15 : 0.55,
    ]);
  }

  setVisible(visible: boolean) {
    this.map.setLayoutProperty(SOURCE, "visibility", visible ? "visible" : "none");
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

export function fitTo(map: Map, features: { geometry: { coordinates: unknown } }[], padding = 40) {
  const b = new LngLatBounds();
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number]);
    else if (Array.isArray(c)) c.forEach(visit);
  };
  features.forEach((f) => visit(f.geometry.coordinates));
  if (!b.isEmpty()) map.fitBounds(b, { padding, maxZoom: 15, duration: 600 });
}
