/**
 * Notable places on the map (« lieux notables », like Komoot's highlights): nature, water, heritage, parks,
 * useful points. Only the visible area is asked for, once the map stops moving; the server sends the best
 * places for the zoom (more detail when zoomed in); in wide views they are grouped (clusters).
 */
import { Popup } from "maplibre-gl";
import type { GeoJSONSource, Map, MapLayerMouseEvent, PointLike } from "maplibre-gl";
import { apiFetch } from "./api";
import type { LngLat } from "./api";
import { escape } from "./format";

export type PoiCategory = "nature" | "water" | "heritage" | "park" | "utility";

export const CATEGORIES: Record<PoiCategory, { label: string; color: string }> = {
  nature: { label: "Nature", color: "#2f7a4a" },
  water: { label: "Eau", color: "#2563a8" },
  heritage: { label: "Patrimoine", color: "#a8661b" },
  park: { label: "Parcs", color: "#5b9a3c" },
  utility: { label: "Points utiles", color: "#6d4fb3" },
};

/** Kind -> [singular, plural] (sheets and « 2 points de vue, 1 cascade »). */
export const KIND_LABELS: Record<string, [string, string]> = {
  viewpoint: ["point de vue", "points de vue"], peak: ["sommet", "sommets"], saddle: ["col", "cols"],
  waterfall: ["cascade", "cascades"], spring: ["source", "sources"], cave: ["grotte", "grottes"],
  rock: ["rocher", "rochers"], reserve: ["espace protégé", "espaces protégés"], river: ["rivière", "rivières"],
  stream: ["ruisseau", "ruisseaux"], lake: ["lac", "lacs"], castle: ["château", "châteaux"], ruins: ["ruines", "ruines"],
  archaeological: ["site archéologique", "sites archéologiques"], monument: ["monument", "monuments"],
  memorial: ["mémorial", "mémoriaux"], church: ["église ou chapelle", "églises et chapelles"], cross: ["croix", "croix"],
  heritage: ["patrimoine", "patrimoine"], park: ["parc", "parcs"], garden: ["jardin", "jardins"],
  drinking_water: ["point d'eau potable", "points d'eau potable"], toilets: ["toilettes", "toilettes"],
  shelter: ["abri", "abris"], hut: ["refuge", "refuges"], picnic: ["aire de pique-nique", "aires de pique-nique"],
};

// White glyphs (24 x 24) drawn on the category's coloured disc.
const GLYPHS: Record<string, string> = {
  viewpoint: "M12 7c-4.5 0-8 5-8 5s3.5 5 8 5 8-5 8-5-3.5-5-8-5zm0 8a3 3 0 1 1 0-6 3 3 0 0 1 0 6z",
  peak: "M3 19l6-10 3 4 2-3 7 9z",
  saddle: "M3 18l4-8 5 5 5-5 4 8z",
  waterfall: "M6 5h12v2H6zM8 9v9M12 9v10M16 9v9",
  spring: "M12 4c-3 5-5 7.5-5 10a5 5 0 0 0 10 0c0-2.5-2-5-5-10z",
  cave: "M4 19c0-7 3.5-12 8-12s8 5 8 12h-5c0-3-1.3-5-3-5s-3 2-3 5z",
  rock: "M5 18l2-8 5-4 6 3 2 9z",
  reserve: "M19 5C9 5 5 10 5 15c0 1.5.4 2.6 1 3.5C8 13 11 10 15 9c-3 2-6 5-7.5 9.5 1 .3 2 .5 3 .5 5 0 8.5-5 8.5-14z",
  river: "M3 9c3-2 6 2 9 0s6 2 9 0M3 15c3-2 6 2 9 0s6 2 9 0",
  stream: "M3 12c3-2 6 2 9 0s6 2 9 0",
  lake: "M3 10c3-2 6 2 9 0s6 2 9 0M3 15c3-2 6 2 9 0s6 2 9 0",
  castle: "M5 20V8h2v2h2V8h2v2h2V8h2v2h2V8h2v12h-5v-4h-4v4z",
  ruins: "M5 20h14v-2H5zM7 17V7h3v4h1v6zM14 17V9h3v8z",
  archaeological: "M4 20h16v-2H4zM6 17V9h2v8zm5 0V9h2v8zm5 0V9h2v8zM4 8l8-4 8 4z",
  monument: "M10 20l1-14 1-2 1 2 1 14zM8 20h8",
  memorial: "M12 3l2.5 5.5 6 .5-4.5 4 1.5 6L12 16l-5.5 3 1.5-6L3.5 9l6-.5z",
  church: "M11 3h2v3h3v2h-3v2l5 4v6h-5v-4h-2v4H6v-6l5-4V8H8V6h3z",
  cross: "M11 3h2v5h5v2h-5v11h-2V10H6V8h5z",
  heritage: "M4 20h16v-2H4zM6 17V9h2v8zm5 0V9h2v8zm5 0V9h2v8zM4 8l8-4 8 4z",
  park: "M12 3a5 5 0 0 0-5 5 4 4 0 0 0 1 7h3v6h2v-6h3a4 4 0 0 0 1-7 5 5 0 0 0-5-5z",
  garden: "M12 4c-2 3-4 4-4 7a4 4 0 0 0 3 3.9V20h2v-5.1A4 4 0 0 0 16 11c0-3-2-4-4-7z",
  drinking_water: "M12 4c-3 5-5 7.5-5 10a5 5 0 0 0 10 0c0-2.5-2-5-5-10zm-2 10a2 2 0 0 0 2 2v2a4 4 0 0 1-4-4z",
  toilets: "M7 6a2 2 0 1 0 0-.1zM17 6a2 2 0 1 0 0-.1zM5 9h4l1 6H8v5H6v-5H4zm10 0h4l2 7h-3v4h-2v-4h-3z",
  shelter: "M3 12l9-7 9 7h-3v7h-3v-5H9v5H6v-7z",
  hut: "M2 13l10-8 10 8h-2.5v7h-5v-5h-5v5h-5v-7z",
  picnic: "M4 9h16v2H4zm2 2l-2 8h2l2-8zm10 0l2 8h2l-2-8zM9 14h6v2H9z",
};

const SOURCE = "pois";
const ICONS = "pois-icons";
const CLUSTERS = "pois-clusters";
const STORE_KEY = "runproject.poiCategories";
const DEBOUNCE_MS = 300;

export interface PoiSheet {
  id: string;
  name: string;
  category: PoiCategory;
  kind: string;
  lon: number;
  lat: number;
  ele?: string | null;
  mhs?: string | null;
  description?: string | null;
  osm_url: string;
  wikipedia?: string | null;
  website?: string | null;
  image?: { thumb: string; page?: string; author: string; license: string; license_url?: string | null } | null;
}

export class PoiLayer {
  enabled: Set<PoiCategory>;
  private timer = 0;
  private abort: AbortController | null = null;
  private cache = new globalThis.Map<string, unknown>();
  private popup: Popup | null = null;

  constructor(
    private map: Map,
    private onVia: (at: LngLat, name: string) => void,
  ) {
    this.enabled = loadCategories();
    addIcons(map);
    map.addSource(SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true, clusterRadius: 42, clusterMaxZoom: 12 });
    map.addLayer({
      id: CLUSTERS,
      type: "circle",
      source: SOURCE,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": "#143f30",
        "circle-opacity": 0.85,
        "circle-radius": ["step", ["get", "point_count"], 13, 10, 16, 50, 20],
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "pois-count",
      type: "symbol",
      source: SOURCE,
      filter: ["has", "point_count"],
      layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12, "text-font": ["Noto Sans Bold"], "text-allow-overlap": true },
      paint: { "text-color": "#fff" },
    });
    map.addLayer({
      id: ICONS,
      type: "symbol",
      source: SOURCE,
      filter: ["!", ["has", "point_count"]],
      layout: {
        "icon-image": ["concat", "poi-", ["get", "kind"]],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.55, 15, 0.75],
        "symbol-sort-key": ["-", 0, ["get", "score"]], // the best places win when icons collide
        "icon-padding": 1,
        "text-field": ["step", ["zoom"], "", 14, ["get", "name"]],
        "text-font": ["Noto Sans Regular"],
        "text-size": 11,
        "text-offset": [0, 1.5],
        "text-anchor": "top",
        "text-optional": true,
        "text-max-width": 9,
      },
      paint: { "text-color": "#1b2420", "text-halo-color": "#fff", "text-halo-width": 1.4 },
    });
    map.on("click", ICONS, (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id as string | undefined;
      if (id) this.open(id);
    });
    map.on("click", CLUSTERS, async (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      if (!f) return;
      const zoom = await (map.getSource(SOURCE) as GeoJSONSource).getClusterExpansionZoom(f.properties?.cluster_id);
      map.easeTo({ center: (f.geometry as { coordinates: [number, number] }).coordinates, zoom });
    });
    for (const layer of [ICONS, CLUSTERS]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }
    map.on("moveend", () => this.schedule());
    this.schedule();
  }

  /** A place (or a group) under this point: the click is for the places, not for the tracks or the planner. */
  hitAt(point: PointLike): boolean {
    return this.map.queryRenderedFeatures(point, { layers: [ICONS, CLUSTERS] }).length > 0;
  }

  setCategories(cats: Set<PoiCategory>) {
    this.enabled = cats;
    saveCategories(cats);
    this.schedule(0);
  }

  private schedule(delay = DEBOUNCE_MS) {
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.load(), delay);
  }

  /** The places of the visible area (a bit beyond), from the cache or the server; the previous request is dropped. */
  private async load() {
    const source = this.map.getSource(SOURCE) as GeoJSONSource;
    if (!this.enabled.size) return source.setData({ type: "FeatureCollection", features: [] });
    const b = this.map.getBounds();
    const pad = 0.1;
    const dx = (b.getEast() - b.getWest()) * pad;
    const dy = (b.getNorth() - b.getSouth()) * pad;
    const step = 0.02; // rounding: small moves reuse the cached answer
    const box = [b.getWest() - dx, b.getSouth() - dy, b.getEast() + dx, b.getNorth() + dy].map((v, i) =>
      (i < 2 ? Math.floor(v / step) : Math.ceil(v / step)) * step,
    );
    const zoom = Math.floor(this.map.getZoom());
    if (zoom < 9) return source.setData({ type: "FeatureCollection", features: [] });
    const cats = [...this.enabled].sort().join(",");
    const key = `${box.map((v) => v.toFixed(2)).join(",")}|${zoom}|${cats}`;
    const hit = this.cache.get(key);
    if (hit) return source.setData(hit as never);
    this.abort?.abort();
    const abort = (this.abort = new AbortController());
    try {
      const params = new URLSearchParams({ bbox: box.map((v) => v.toFixed(4)).join(","), zoom: String(zoom), categories: cats });
      const r = await apiFetch(`/api/pois?${params}`, { signal: abort.signal });
      if (!r.ok) return;
      const fc = await r.json();
      this.cache.set(key, fc);
      if (this.cache.size > 40) this.cache.delete(this.cache.keys().next().value!);
      if (!abort.signal.aborted) source.setData(fc);
    } catch {
      /* aborted by a newer move, or offline: the map stays as it is */
    }
  }

  /** The sheet of a place, at its position (from the map, or from the list under a route). */
  async open(id: string, fly = false) {
    const r = await apiFetch(`/api/pois/${encodeURIComponent(id)}`);
    if (!r.ok) return;
    const p = (await r.json()) as PoiSheet;
    const phone = matchMedia("(max-width: 700px)").matches;
    if (fly) this.map.jumpTo({ zoom: Math.max(this.map.getZoom(), 15), ...(phone ? { center: [p.lon, p.lat] } : {}) });
    this.popup?.remove();
    const cat = CATEGORIES[p.category];
    const kind = KIND_LABELS[p.kind]?.[0] ?? cat.label;
    const img = p.image;
    const el = document.createElement("div");
    el.className = "poi-sheet";
    el.innerHTML = `
      ${img ? `<figure><img src="${escape(img.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer" />
        <figcaption>Photo : ${escape(img.author)}, ${img.license_url ? `<a href="${escape(img.license_url)}" target="_blank" rel="noopener">${escape(img.license)}</a>` : escape(img.license)}${img.page ? ` · <a href="${escape(img.page)}" target="_blank" rel="noopener">Wikimedia Commons</a>` : ""}</figcaption></figure>` : ""}
      <p class="poi-kind" style="--c:${cat.color}"><span class="dot"></span>${escape(kind.charAt(0).toUpperCase() + kind.slice(1))}${p.ele ? ` · ${escape(p.ele)} m` : ""}</p>
      <h3>${escape(p.name || kind.charAt(0).toUpperCase() + kind.slice(1))}</h3>
      ${p.mhs ? `<p class="poi-mhs">Monument historique</p>` : ""}
      ${p.description ? `<p class="poi-desc">${escape(p.description)}</p>` : ""}
      <p class="poi-links">
        ${p.wikipedia ? `<a href="${escape(p.wikipedia)}" target="_blank" rel="noopener">Wikipédia</a>` : ""}
        <a href="${escape(p.osm_url)}" target="_blank" rel="noopener">OpenStreetMap</a>
      </p>
      <button type="button" class="action watch poi-via">Passer par ici</button>
      <p class="poi-credit">© OpenStreetMap contributors${img ? " · photo : Wikimedia Commons" : ""}</p>`;
    el.querySelector(".poi-via")!.addEventListener("click", () => {
      this.onVia([p.lon, p.lat], p.name || kind);
      this.close();
    });
    if (phone) {
      // Phone: a sheet over the app (a map bubble this tall would slide under the bottom panel).
      const dialog = document.getElementById("poi-dialog") as HTMLDialogElement;
      const body = dialog.querySelector(".poi-dialog-body")!;
      body.replaceChildren(el);
      (dialog.querySelector(".poi-close") as HTMLButtonElement).onclick = () => dialog.close();
      dialog.onclick = (e) => e.target === dialog && dialog.close(); // a tap outside closes it
      if (!dialog.open) dialog.showModal();
      return;
    }
    // Computer: a bubble opening upwards, the place moved to the lower part of the map so it fits.
    this.map.easeTo({ center: [p.lon, p.lat], offset: [0, this.map.getContainer().clientHeight * 0.25], duration: 300 });
    this.popup = new Popup({ maxWidth: "280px", offset: 14, anchor: "bottom" }).setLngLat([p.lon, p.lat]).setDOMContent(el).addTo(this.map);
  }

  private close() {
    this.popup?.remove();
    const dialog = document.getElementById("poi-dialog") as HTMLDialogElement;
    if (dialog.open) dialog.close();
  }

  /** Fly to a place and open its sheet (list under a route). */
  show(id: string) {
    this.open(id, true);
  }
}

/** One icon per kind: the category's disc with the kind's white glyph (drawn once, as SVG images). */
function addIcons(map: Map) {
  const kindCategory: Record<string, PoiCategory> = {
    viewpoint: "nature", peak: "nature", saddle: "nature", spring: "nature", cave: "nature", rock: "nature", reserve: "nature",
    waterfall: "water", river: "water", stream: "water", lake: "water",
    castle: "heritage", ruins: "heritage", archaeological: "heritage", monument: "heritage", memorial: "heritage",
    church: "heritage", cross: "heritage", heritage: "heritage", park: "park", garden: "park",
    drinking_water: "utility", toilets: "utility", shelter: "utility", hut: "utility", picnic: "utility",
  };
  for (const [kind, cat] of Object.entries(kindCategory)) {
    const d = GLYPHS[kind];
    const stroke = /^(river|stream|lake|waterfall)$/.test(kind);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="56" height="56" viewBox="-4 -4 32 32">
      <circle cx="12" cy="12" r="14" fill="${CATEGORIES[cat].color}" stroke="#fff" stroke-width="2.2"/>
      <path d="${d}" transform="translate(3.6 3.6) scale(0.7)" ${stroke ? 'fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"' : 'fill="#fff"'}/></svg>`;
    const img = new Image(56, 56);
    img.onload = () => !map.hasImage(`poi-${kind}`) && map.addImage(`poi-${kind}`, img, { pixelRatio: 2 });
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }
}

function loadCategories(): Set<PoiCategory> {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? "null");
    if (Array.isArray(saved)) return new Set(saved.filter((c) => c in CATEGORIES));
  } catch {
    /* default below */
  }
  return new Set(Object.keys(CATEGORIES) as PoiCategory[]);
}

function saveCategories(cats: Set<PoiCategory>) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify([...cats]));
  } catch {
    /* not kept: all categories next time */
  }
}

/** « 2 points de vue, 1 cascade, 1 point d'eau potable » */
export function summarize(pois: { kind: string }[]): string {
  const counts = new globalThis.Map<string, number>();
  pois.forEach((p) => counts.set(p.kind, (counts.get(p.kind) ?? 0) + 1));
  return [...counts]
    .map(([kind, n]) => {
      const [one, many] = KIND_LABELS[kind] ?? [kind, kind];
      return `${n} ${n > 1 ? many : one}`;
    })
    .join(", ");
}
