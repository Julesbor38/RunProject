import { Marker } from "maplibre-gl";
import type { Map, MapMouseEvent, PointLike } from "maplibre-gl";
import { apiFetch, cancelRoute, fetchRouteProgress, fetchRoutes, gpxUrl } from "./api";
import type { LngLat, Preferences, RouteCollection, RouteFeature, RouteProgress } from "./api";
import { fitTo } from "./activities";
import { isMobile, km, pct } from "./format";
import { pointAt, renderProfile } from "./profile";

const ROUTE_COLORS = ["#2563eb", "#ea580c", "#db2777"];
const STORAGE_PREFIX = "trailmap.planner."; // + user: accounts sharing a browser don't see each other's start

interface PrefDef {
  key: keyof BasePrefs;
  label: string;
  left: string;
  right: string;
  min: number;
}

const PREFS: PrefDef[] = [
  { key: "nature", label: "Sentiers nature", left: "Indifférent", right: "Au maximum", min: 0 },
  { key: "avoid_traffic", label: "Circulation", left: "Indifférent", right: "À éviter", min: 0 },
  { key: "lit", label: "Éclairage", left: "Indifférent", right: "Indispensable", min: 0 },
  { key: "avoid_steps", label: "Escaliers", left: "Indifférent", right: "À éviter", min: 0 },
  { key: "familiarity", label: "Chemins", left: "Découverte", right: "Déjà courus", min: -1 },
];

type BasePrefs = Omit<Preferences, "hills">;

const PRESETS: { label: string; prefs: BasePrefs }[] = [
  { label: "Équilibré", prefs: { nature: 0.5, avoid_traffic: 0.7, lit: 0, familiarity: 0, avoid_steps: 0.3 } },
  { label: "Trail nature", prefs: { nature: 1, avoid_traffic: 1, lit: 0, familiarity: 0, avoid_steps: 0 } },
  { label: "Sortie de nuit", prefs: { nature: 0, avoid_traffic: 0.6, lit: 1, familiarity: 0.6, avoid_steps: 0.6 } },
  { label: "Découverte", prefs: { nature: 0.5, avoid_traffic: 0.7, lit: 0, familiarity: -1, avoid_steps: 0.3 } },
];

type AscentMode = "any" | "flat" | "rolling" | "mountain" | "custom";

// D+ per km of loop, and how strongly the router seeks (+) or avoids (-) climbs.
const ASCENT: Record<Exclude<AscentMode, "custom">, { label: string; perKm?: [number, number]; hills: number }> = {
  any: { label: "Indifférent", hills: 0 },
  flat: { label: "Le plus plat", hills: -1 }, // no range: the server minimizes the climb (small loops allowed)
  rolling: { label: "Vallonné", perKm: [15, 35], hills: 0.2 },
  mountain: { label: "Montagne", perKm: [40, 200], hills: 1 },
};

type Mode = "loop" | "oneway";

interface Saved {
  mode: Mode;
  distance: number;
  prefs: BasePrefs;
  start: LngLat | null;
  ascent?: { mode: AscentMode; min: number; max: number };
  onewayTarget?: boolean;
}

/** The "Itinéraire" tab: start/end points, preferences, generated routes. */
export class Planner {
  active = true;
  private mode: Mode = "loop";
  private distance = 10;
  private onewayTarget = false; // one-way: aim for `distance` instead of the best direct route
  private prefs: BasePrefs = { ...PRESETS[0].prefs };
  private ascentMode: AscentMode = "any";
  private customAscent: [number, number] = [150, 350];
  private hoverMarker: Marker | null = null;
  private start: Marker | null = null;
  private end: Marker | null = null;
  private routes: RouteFeature[] = [];
  private flatResults = false; // the shown routes come from « Le plus plat »
  private selected = 0;
  private busy = false;
  private generation: { id: string; abort: AbortController } | null = null; // the one running, cancellable
  private picking: "start" | "end" | null = null;

  private storageKey: string;

  constructor(
    private map: Map,
    private onRoutesShown: (shown: boolean) => void,
    user: string,
  ) {
    this.storageKey = STORAGE_PREFIX + user;
    this.restore();
    this.addLayers();
    this.renderMode();
    this.renderOnewayLength();
    this.renderDistance();
    this.renderAscent();
    this.renderPresets();
    this.renderPrefs();
    this.renderPoints();

    map.on("click", (e: MapMouseEvent) => {
      if (!this.active || this.busy) return;
      if (map.queryRenderedFeatures(e.point, { layers: ["routes"] }).length) return; // selecting a route
      const at = e.lngLat.toArray() as LngLat;
      // A click places a missing point, or moves the one being picked; placed points are otherwise dragged.
      const target = this.picking ?? (!this.start ? "start" : this.mode === "oneway" && !this.end ? "end" : null);
      if (target === "start") this.setStart(at);
      else if (target === "end") this.setEnd(at);
      this.setPicking(null);
    });
    document.getElementById("place-start")!.addEventListener("click", () => this.place("start"));
    document.getElementById("place-end")!.addEventListener("click", () => this.place("end"));
    document.getElementById("locate")!.addEventListener("click", () => this.locate());
    document.getElementById("generate")!.addEventListener("click", () => this.generate());
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (this.generation) this.cancel();
      else this.setPicking(null);
    });
    this.updateButton();
  }

  /** Whether a map click there is the planner's: placing or moving a point, or picking a route. */
  claimsClick(point: PointLike): boolean {
    if (!this.active || this.busy) return false;
    if (this.map.queryRenderedFeatures(point, { layers: ["routes"] }).length) return true;
    return this.picking !== null || !this.start || (this.mode === "oneway" && !this.end);
  }

  setActive(active: boolean) {
    this.active = active;
    if (!active) this.setPicking(null);
  }

  /** Drop the point at the map center right away, then let the next map click move it. */
  private place(which: "start" | "end") {
    const center = this.map.getCenter().toArray() as LngLat;
    if (which === "start" && !this.start) this.setStart(center);
    if (which === "end" && !this.end) this.setEnd(this.offsetFromStart(center));
    this.setPicking(which);
  }

  /** Avoid dropping B exactly on A when both are placed from the same view. */
  private offsetFromStart(center: LngLat): LngLat {
    const a = this.start?.getLngLat();
    if (!a || Math.abs(a.lng - center[0]) + Math.abs(a.lat - center[1]) > 1e-4) return center;
    const p = this.map.project(center);
    return this.map.unproject([p.x + 120, p.y]).toArray() as LngLat;
  }

  private setPicking(which: "start" | "end" | null) {
    this.picking = which;
    this.map.getCanvas().style.cursor = which ? "crosshair" : "";
    document.getElementById("place-start")!.classList.toggle("on", which === "start");
    document.getElementById("place-end")!.classList.toggle("on", which === "end");
    if (which) this.status(`Cliquez sur la carte pour placer ${which === "start" ? "le départ" : "l'arrivée"}, ou faites glisser le point. Échap pour annuler.`);
    else if (!this.busy) this.status(null);
  }

  private addLayers() {
    this.map.addSource("routes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    this.map.addLayer({
      id: "routes-casing",
      type: "line",
      source: "routes",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#ffffff",
        "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 10, 6],
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 1, 0.6],
      },
    });
    this.map.addLayer({
      id: "routes",
      type: "line",
      source: "routes",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": ["match", ["id"], 0, ROUTE_COLORS[0], 1, ROUTE_COLORS[1], ROUTE_COLORS[2]] as never,
        "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 6, 3],
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 1, 0.55],
      },
    });
    this.map.on("click", "routes", (e) => {
      const id = e.features?.[0]?.id as number | undefined;
      if (id !== undefined) this.select(id);
    });
    if (this.saved?.start) this.setStart(this.saved.start, false);
  }

  // --- points ---

  private setStart(at: LngLat, clear = true) {
    if (!this.start) {
      this.start = makeMarker("A", "start").setLngLat(at).addTo(this.map);
      this.start.on("dragend", () => this.pointsChanged());
    } else this.start.setLngLat(at);
    if (clear) this.pointsChanged();
    else this.renderPoints();
  }

  private setEnd(at: LngLat) {
    if (!this.end) {
      this.end = makeMarker("B", "end").setLngLat(at).addTo(this.map);
      this.end.on("dragend", () => this.pointsChanged());
    } else this.end.setLngLat(at);
    this.pointsChanged();
  }

  private pointsChanged() {
    this.clearRoutes();
    this.renderPoints();
    this.updateButton();
    this.save();
  }

  private locate() {
    if (!window.isSecureContext)
      return this.status(
        `La position n'est disponible que sur http://localhost:${location.port || 80} (le navigateur la bloque sur une adresse IP). En attendant, utilisez « Placer sur la carte ».`,
        true,
      );
    if (!navigator.geolocation) return this.status("Géolocalisation indisponible dans ce navigateur.", true);
    this.status("Recherche de votre position…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const at: LngLat = [pos.coords.longitude, pos.coords.latitude];
        this.setStart(at);
        this.map.flyTo({ center: at, zoom: 14 });
        this.status(null);
      },
      () => this.status("Position refusée ou introuvable.", true),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  // --- generation ---

  private async generate() {
    if (this.generation) return this.cancel();
    if (this.busy) return;
    if (!this.start || (this.mode === "oneway" && !this.end)) {
      const which = !this.start ? "start" : "end";
      this.place(which);
      this.status(
        `${which === "start" ? "Départ placé" : "Arrivée placée"} au centre de la carte : déplacez-le si besoin (clic ou glisser), puis cliquez de nouveau sur « Générer ».`,
      );
      return;
    }
    this.setPicking(null);
    const start = this.start.getLngLat().toArray() as LngLat;
    const end = this.mode === "oneway" ? (this.end?.getLngLat().toArray() as LngLat | undefined) : undefined;
    const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const abort = new AbortController();
    this.generation = { id, abort };
    this.busy = true;
    this.updateButton();
    this.status("Calcul en cours… (Échap ou « Annuler » pour arrêter)");
    const poll = window.setInterval(async () => {
      const p = await fetchRouteProgress(id).catch(() => null);
      if (p && !abort.signal.aborted) this.status(progressText(p));
    }, 1000);
    try {
      const range = this.withDistance ? this.ascentRange() : null;
      const fc = await fetchRoutes(
        {
          start,
          end,
          distance_km: this.withDistance ? this.distance : undefined,
          ascent_min_m: range?.[0],
          ascent_max_m: range && Number.isFinite(range[1]) ? range[1] : undefined,
          preferences: { ...this.prefs, hills: this.hills() },
          request_id: id,
          flat: this.ascentMode === "flat",
        },
        abort.signal,
      );
      this.flatResults = this.ascentMode === "flat";
      this.showRoutes(fc);
      const missed = range && fc.features.every((f) => f.properties.in_ascent_range === false);
      const direct = this.mode === "oneway" && this.onewayTarget && fc.features.length === 1 ? fc.features[0].properties.distance_m : null;
      const note =
        direct !== null
          ? `Le trajet le plus direct fait déjà ${km(direct)}, au moins les ${this.distance} km visés : voici ce trajet.`
          : missed
            ? `Le terrain ne permet pas ${this.mode === "loop" ? "de boucle" : "d'itinéraire"} de ${this.distance} km dans la tranche ${rangeText(range)} ici : voici les plus proches.` +
              (fc.features.some((f) => f.properties.ascent_m > range[1]) ? " Pour le moins de dénivelé possible, choisissez « Le plus plat »." : "")
            : null;
      this.status([note, fc.warning].filter(Boolean).join(" ") || null, false);
    } catch (e) {
      if (abort.signal.aborted) this.status("Génération annulée.");
      else this.status(`Impossible de générer l'itinéraire : ${(e as Error).message}`, true);
    } finally {
      window.clearInterval(poll);
      this.generation = null;
      this.busy = false;
      this.updateButton();
    }
  }

  /** Stop the running generation: the page gives up at once, the server at its next step. */
  private cancel() {
    const g = this.generation;
    if (!g) return;
    g.abort.abort();
    cancelRoute(g.id).catch(() => {});
  }

  private showRoutes(fc: RouteCollection) {
    this.routes = fc.features;
    (this.map.getSource("routes") as never as { setData(d: unknown): void }).setData(fc);
    this.onRoutesShown(true);
    this.select(0, false);
    fitTo(this.map, fc.features, 60);
    this.renderResults();
    document.getElementById("results")!.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  private clearRoutes() {
    this.showHoverPoint(this.routes[0], null);
    if (!this.routes.length) return;
    this.routes = [];
    (this.map.getSource("routes") as never as { setData(d: unknown): void }).setData({ type: "FeatureCollection", features: [] });
    this.onRoutesShown(false);
    this.renderResults();
  }

  private select(id: number, render = true) {
    this.routes.forEach((r) => this.map.setFeatureState({ source: "routes", id: r.id }, { selected: r.id === id }));
    this.selected = id;
    if (render) this.renderResults();
  }

  // --- rendering ---

  private renderMode() {
    const box = document.getElementById("mode")!;
    box.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === this.mode);
      b.onclick = () => {
        this.mode = b.dataset.mode as Mode;
        if (this.mode === "loop" && this.end) {
          this.end.remove();
          this.end = null;
        }
        this.renderMode();
        this.renderAscent();
        this.pointsChanged();
      };
    });
    document.getElementById("end-row")!.hidden = this.mode !== "oneway";
    document.getElementById("oneway-length-field")!.hidden = this.mode !== "oneway";
    document.getElementById("distance-field")!.hidden = !this.withDistance;
  }

  /** Loops always have a target distance; one-way routes only when asked. */
  private get withDistance() {
    return this.mode === "loop" || this.onewayTarget;
  }

  private renderOnewayLength() {
    document.querySelectorAll<HTMLButtonElement>("#oneway-length button").forEach((b) => {
      b.classList.toggle("on", (b.dataset.length === "target") === this.onewayTarget);
      b.onclick = () => {
        this.onewayTarget = b.dataset.length === "target";
        this.renderOnewayLength();
        this.renderMode();
        this.renderAscent();
        this.save();
      };
    });
  }

  private renderDistance() {
    const input = document.getElementById("distance") as HTMLInputElement;
    const value = document.getElementById("distance-value")!;
    input.value = String(this.distance);
    value.textContent = `${this.distance} km`;
    input.oninput = () => {
      this.distance = Number(input.value);
      value.textContent = `${this.distance} km`;
      this.renderAscent();
      this.save();
    };
  }

  /** Wanted D+ range in meters for the current distance, or null for "any". */
  private ascentRange(): [number, number] | null {
    if (this.ascentMode === "custom") return this.customAscent;
    const perKm = ASCENT[this.ascentMode].perKm;
    if (!perKm) return null;
    const hi = this.ascentMode === "mountain" ? Infinity : Math.round((perKm[1] * this.distance) / 10) * 10;
    return [Math.round((perKm[0] * this.distance) / 10) * 10, hi];
  }

  private hills(): number {
    if (this.ascentMode !== "custom") return ASCENT[this.ascentMode].hills;
    const midPerKm = (this.customAscent[0] + this.customAscent[1]) / 2 / this.distance;
    return Math.max(-1, Math.min(1, (midPerKm - 20) / 20));
  }

  private renderAscent() {
    const box = document.getElementById("ascent-presets")!;
    box.innerHTML = "";
    const modes: AscentMode[] = ["any", "flat", "rolling", "mountain", "custom"];
    modes.forEach((mode) => {
      const b = document.createElement("button");
      b.className = "chip" + (mode === this.ascentMode ? " on" : "");
      b.textContent = mode === "custom" ? "Personnalisé" : ASCENT[mode].label;
      b.onclick = () => {
        if (mode === "custom" && this.ascentMode !== "custom") {
          const current = this.ascentRange();
          if (current) this.customAscent = [current[0], Number.isFinite(current[1]) ? current[1] : current[0] + 300];
        }
        this.ascentMode = mode;
        this.renderAscent();
        this.save();
      };
      box.appendChild(b);
    });
    const range = this.ascentRange();
    document.getElementById("ascent-value")!.textContent =
      this.ascentMode === "flat"
        ? "D+ minimal"
        : !this.withDistance
          ? this.ascentMode === "any" ? "Indifférent" : ASCENT[this.ascentMode === "custom" ? "rolling" : this.ascentMode].label
          : range ? rangeText(range) : "Indifférent";
    const custom = document.getElementById("ascent-custom")!;
    custom.hidden = this.ascentMode !== "custom" || !this.withDistance;
    const [minInput, maxInput] = ["ascent-min", "ascent-max"].map((id) => document.getElementById(id) as HTMLInputElement);
    minInput.value = String(this.customAscent[0]);
    maxInput.value = String(this.customAscent[1]);
    const onInput = () => {
      const lo = Math.max(0, Number(minInput.value) || 0);
      const hi = Math.max(lo, Number(maxInput.value) || lo);
      this.customAscent = [lo, hi];
      document.getElementById("ascent-value")!.textContent = rangeText(this.customAscent);
      this.save();
    };
    minInput.oninput = maxInput.oninput = onInput;
  }

  private renderPresets() {
    const box = document.getElementById("presets")!;
    box.innerHTML = "";
    PRESETS.forEach((preset) => {
      const b = document.createElement("button");
      b.className = "chip";
      b.textContent = preset.label;
      b.classList.toggle("on", samePrefs(preset.prefs, this.prefs));
      b.onclick = () => {
        this.prefs = { ...preset.prefs };
        this.renderPrefs();
        this.renderPresets();
        this.save();
      };
      box.appendChild(b);
    });
  }

  private renderPrefs() {
    const box = document.getElementById("prefs")!;
    box.innerHTML = "";
    PREFS.forEach((def) => {
      const field = document.createElement("label");
      field.className = "field pref";
      field.innerHTML = `
        <span class="field-head">${def.label}</span>
        <input type="range" min="${def.min}" max="1" step="0.1" value="${this.prefs[def.key]}" class="${def.min < 0 ? "bipolar" : ""}">
        <span class="range-ends"><span>${def.left}</span><span>${def.right}</span></span>`;
      field.querySelector("input")!.addEventListener("input", (e) => {
        this.prefs[def.key] = Number((e.target as HTMLInputElement).value);
        this.renderPresets();
        this.save();
      });
      box.appendChild(field);
    });
  }

  private renderPoints() {
    const fmt = (m: Marker | null, empty: string) => {
      if (!m) return empty;
      const { lng, lat } = m.getLngLat();
      return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    };
    document.getElementById("start-label")!.textContent = fmt(this.start, "Départ : pas encore placé");
    document.getElementById("end-label")!.textContent = fmt(this.end, "Arrivée : pas encore placée");
    document.querySelector("#place-start .label")!.textContent = this.start ? "Déplacer le départ" : "Placer sur la carte";
    document.querySelector("#place-end .label")!.textContent = this.end ? "Déplacer l'arrivée" : "Placer l'arrivée sur la carte";
  }

  private renderResults() {
    const box = document.getElementById("results")!;
    box.innerHTML = "";
    this.routes.forEach((r) => {
      const p = r.properties;
      const card = document.createElement("article");
      card.className = "route-card" + (r.id === this.selected ? " selected" : "");
      card.style.setProperty("--c", ROUTE_COLORS[r.id] ?? ROUTE_COLORS[2]);
      const letter = String.fromCharCode(65 + r.id);
      const title = `${this.mode === "loop" ? "Boucle" : "Itinéraire"}${this.mode === "loop" || this.routes.length > 1 ? ` ${letter}` : ""}`;
      card.innerHTML = `
        <header>
          <span class="route-letter">${letter}</span>
          <strong class="route-title">${title}</strong>
          <span class="dist">${(p.distance_m / 1000).toFixed(1).replace(".", ",")}<small> km</small></span>
        </header>
        <p class="climb">
          <span title="Dénivelé positif"><svg class="i"><use href="#i-up"/></svg>${p.ascent_m} m</span>
          <span title="Dénivelé négatif"><svg class="i"><use href="#i-down"/></svg>${p.descent_m} m</span>
          ${p.petals > 1 ? `<span title="Plusieurs boucles depuis le départ, pour rester sur le terrain le plus plat"><svg class="i"><use href="#i-loop"/></svg>${p.petals} boucles</span>` : ""}
          ${this.flatResults ? `<span class="muted" title="Dénivelé positif par kilomètre">${Math.round((p.ascent_m / p.distance_m) * 1000)} m/km</span>` : ""}
          ${p.ele_min != null ? `<span class="muted" title="Altitudes min – max"><svg class="i"><use href="#i-peak"/></svg>${Math.round(p.ele_min)}–${Math.round(p.ele_max ?? 0)} m</span>` : ""}
          ${p.in_ascent_range === false ? `<span class="badge">hors tranche</span>` : ""}
        </p>
        ${r.id === this.selected && p.profile.length ? `<div class="profile"></div>` : ""}
        <div class="bars">
          ${bar("Nature", p.nature)}
          ${bar("Éclairé", p.lit)}
          ${bar("Déjà couru", p.familiar)}
          ${bar("Routes passantes", p.busy_roads, true)}
        </div>
        <div class="actions">
          <a class="action gpx" href="${gpxUrl(p.route_id)}" download="${p.gpx_filename}"><svg class="i"><use href="#i-download"/></svg>GPX</a>
          <button class="action watch" hidden title="Télécharger le GPX dans Safari, puis l'ouvrir avec l'app COROS depuis Fichiers"><svg class="i"><use href="#i-watch"/></svg>Envoyer vers la montre</button>
        </div>`;
      card.addEventListener("click", () => this.select(r.id));
      const profileBox = card.querySelector(".profile") as HTMLElement | null;
      if (profileBox) {
        profileBox.addEventListener("click", (e) => e.stopPropagation());
        renderProfile(profileBox, p.profile, ROUTE_COLORS[r.id] ?? ROUTE_COLORS[2], (d) => this.showHoverPoint(r, d));
      }
      // Phone: the GPX opens in Safari next to the app (never in place of it: in an app added to the iOS home
      // screen there would be no way back). Safari downloads it, then Fichiers -> Partager -> COROS, the only
      // way COROS takes a GPX. Safari has no session there: the link is signed and valid for an hour.
      const watch = card.querySelector(".watch") as HTMLButtonElement;
      watch.hidden = !isMobile();
      const link = isMobile() ? prefetchLink(p.route_id) : null;
      const send = (e: Event) => {
        e.stopPropagation();
        if (!link) return; // desktop: the link downloads the file
        e.preventDefault();
        const url = link.fresh();
        if (!url) {
          this.status(link.failed ? "GPX indisponible : régénérez l'itinéraire." : "GPX en préparation : réessayez dans un instant.", link.failed);
          return;
        }
        window.open(url, "_blank"); // in the tap itself, or Safari blocks it
        this.status("Une page s'ouvre : « Télécharger le GPX », puis Fichiers → Téléchargements → Partager ⬆ → COROS. La croix en haut à gauche ramène ici.");
      };
      watch.addEventListener("click", send);
      card.querySelector(".gpx")!.addEventListener("click", send);
      box.appendChild(card);
    });
  }

  private showHoverPoint(r: RouteFeature, distanceM: number | null) {
    if (distanceM === null) {
      this.hoverMarker?.remove();
      this.hoverMarker = null;
      return;
    }
    if (!this.hoverMarker) {
      const el = document.createElement("div");
      el.className = "hover-point";
      el.style.setProperty("--c", ROUTE_COLORS[r.id] ?? ROUTE_COLORS[2]);
      this.hoverMarker = new Marker({ element: el });
    }
    this.hoverMarker.setLngLat(pointAt(r.geometry.coordinates, distanceM)).addTo(this.map);
  }

  private updateButton() {
    const b = document.getElementById("generate") as HTMLButtonElement;
    b.disabled = this.busy && !this.generation;
    b.classList.toggle("cancel", !!this.generation);
    b.textContent = this.generation ? "Annuler le calcul" : this.routes.length ? "Régénérer" : "Générer l'itinéraire";
  }

  private status(text: string | null, error = false) {
    const el = document.getElementById("route-status")!;
    el.hidden = !text;
    el.textContent = text ?? "";
    el.classList.toggle("error", error);
  }

  // --- persistence (per-browser convenience only) ---

  private saved: Saved | null = null;

  private restore() {
    try {
      localStorage.removeItem("trailmap.planner"); // from before accounts: one shared key
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) return;
      this.saved = JSON.parse(raw) as Saved;
      this.mode = this.saved.mode === "oneway" ? "oneway" : "loop";
      this.distance = this.saved.distance ?? this.distance;
      this.onewayTarget = this.saved.onewayTarget ?? false;
      this.prefs = { ...this.prefs, ...this.saved.prefs };
      if (this.saved.ascent) {
        this.ascentMode = this.saved.ascent.mode;
        this.customAscent = [this.saved.ascent.min, this.saved.ascent.max];
      }
    } catch {
      this.saved = null;
    }
  }

  private save() {
    try {
      const data: Saved = {
        mode: this.mode,
        distance: this.distance,
        prefs: this.prefs,
        start: this.start ? (this.start.getLngLat().toArray() as LngLat) : null,
        ascent: { mode: this.ascentMode, min: this.customAscent[0], max: this.customAscent[1] },
        onewayTarget: this.onewayTarget,
      };
      localStorage.setItem(this.storageKey, JSON.stringify(data));
    } catch {
      /* storage unavailable: settings just won't persist */
    }
  }

  get startPoint(): LngLat | null {
    return this.start ? (this.start.getLngLat().toArray() as LngLat) : null;
  }
}

/** A signed link to the route's GPX, fetched in the background so that a tap can open it at once. */
function prefetchLink(routeId: string) {
  const out = {
    url: null as string | null,
    failed: false,
    expires: 0,
    /** The link, or null (and a new one on its way) when missing or about to expire. */
    fresh(): string | null {
      if (this.url && this.expires - Date.now() / 1000 > 60) return this.url;
      if (this.url) this.refresh();
      return null;
    },
    refresh() {
      this.url = null;
      this.failed = false;
      apiFetch(`/api/routes/${encodeURIComponent(routeId)}/link`, { method: "POST" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`erreur ${r.status}`))))
        .then((body: { url: string; expires: number }) => Object.assign(this, { url: body.url, expires: body.expires }))
        .catch(() => (this.failed = true));
    },
  };
  out.refresh();
  return out;
}

function makeMarker(label: string, kind: "start" | "end") {
  const el = document.createElement("div");
  el.className = `pin ${kind} marker`;
  el.textContent = label;
  return new Marker({ element: el, draggable: true });
}

function bar(label: string, value: number, bad = false) {
  return `<div class="bar${bad ? " bad" : ""}"><span>${label}</span><div class="track"><div style="width:${Math.round(value * 100)}%"></div></div><span class="v">${pct(value)}</span></div>`;
}

function samePrefs(a: BasePrefs, b: BasePrefs) {
  return (Object.keys(a) as (keyof BasePrefs)[]).every((k) => Math.abs(a[k] - b[k]) < 1e-6);
}

function progressText(p: RouteProgress) {
  const hint = " (Échap pour annuler)";
  switch (p.stage) {
    case "download_ends":
      return `Téléchargement des chemins autour du départ et de l'arrivée (zone jamais utilisée, jusqu'à 3 min si OpenStreetMap est saturé)…${hint}`;
    case "download":
      return `Téléchargement des chemins OpenStreetMap de la zone : ${p.done}/${p.total}…${hint}`;
    case "graph":
      return `Préparation du réseau de chemins…${hint}`;
    case "routes":
      return p.total ? `Recherche des itinéraires : essai ${p.done}/${p.total}…${hint}` : `Recherche du trajet direct…${hint}`;
    default:
      return `Calcul en cours…${hint}`;
  }
}

function rangeText([lo, hi]: [number, number]) {
  if (!Number.isFinite(hi)) return `D+ ≥ ${lo} m`;
  return lo === 0 ? `D+ ≤ ${hi} m` : `D+ ${lo}–${hi} m`;
}
