import { Map, NavigationControl, ScaleControl, GeolocateControl, setWorkerUrl } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { ActivitiesView } from "./activities";
import { fetchActivities, fetchRoutingStatus } from "./api";
import { ensureLoggedIn, signOut } from "./auth";
import { setupDebug } from "./debug";
import { ensureServer } from "./native";
import { openImporter, setupImporter, takeNewActivities } from "./importer";
import { Planner } from "./planner";
import { PoiLayer } from "./pois";
import { ExploreView } from "./explore";
import { Ratings } from "./ratings";
import { addTerrain } from "./terrain";

// The production bundle doesn't ship MapLibre's sibling worker file: point it at the one Vite bundles.
// (In dev, MapLibre isn't pre-bundled and finds its worker next to itself.)
if (import.meta.env.PROD) setWorkerUrl(maplibreWorkerUrl);

type Tab = "route" | "activities" | "explore";

const panel = document.getElementById("panel")!;
const summary = document.getElementById("summary")!;

const map = new Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  center: [4.8357, 45.764],
  zoom: 11,
  attributionControl: { compact: true }, // a small ⓘ: keeps the bottom of the map free on phones
});
// Handy from the browser console (dev), and for driving the map in tests (?debug=1).
if (import.meta.env.DEV || new URLSearchParams(location.search).get("debug") === "1") Object.assign(window, { map });
map.addControl(new NavigationControl(), "top-right");
map.addControl(new GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");
map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");

setupDebug(); // ?debug=1 or a long press on the title

// Nothing of the user's data is requested before login (the base map is public).
// Native app: first make sure the server answers (its address, or « Active Tailscale sur ton iPhone »).
const loggedIn = ensureServer().then(ensureLoggedIn);
const data = loggedIn.then(fetchActivities);
const ratings = new Ratings();
const ratingsLoaded = loggedIn.then(() => ratings.load()).catch(() => undefined); // the map works without them
loggedIn.then((user) => {
  const out = document.getElementById("sign-out")!;
  out.hidden = false;
  out.title = `Se déconnecter (${user})`;
  out.addEventListener("click", signOut);
  setupImporter();
  pollOsmStatus();
});

map.on("load", async () => {
  addTerrain(map);
  let activities: ActivitiesView | null = null;
  const newKeys = new Set(takeNewActivities());
  try {
    await ratingsLoaded;
    activities = new ActivitiesView(map, await data, (text) => (summary.textContent = text), ratings, newKeys);
  } catch (e) {
    summary.textContent = `API injoignable (${(e as Error).message}) : le backend tourne-t-il sur :8000 ?`;
  }
  const planner = new Planner(map, (shown) => activities?.setMuted(shown), await loggedIn);
  // Notable places: above the tracks and the routes; « Passer par ici » adds a point de passage.
  const pois = new PoiLayer(map, (at, name) => planner.addVia(at, name));
  planner.pois = pois;
  planner.renderPoiFilters();
  // Exploration: « Explorer » opens the generator on that zone, in Découverte mode.
  const explore = new ExploreView(
    map,
    (at) => {
      showTab("route");
      planner.discover(at);
    },
    (visible) => activities?.setVisible(visible && (document.getElementById("show-tracks") as HTMLInputElement).checked),
  );

  const showTab = (tab: Tab) => {
    document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.getElementById("tab-route")!.hidden = tab !== "route";
    document.getElementById("tab-activities")!.hidden = tab !== "activities";
    document.getElementById("tab-explore")!.hidden = tab !== "explore";
    if (tab === "explore") explore.refresh();
    planner.setActive(tab === "route");
    // Tracks open their sheet (and rating) on click in both tabs, unless the planner needs that click.
    if (activities) activities.clickable = (point) => (tab === "activities" ? !pois.hitAt(point) : !planner.claimsClick(point));
  };
  document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab as Tab)));
  // After an import: straight to the new activities. A new account: straight to adding its data.
  const empty = activities !== null && (await data).features.length === 0;
  showTab(newKeys.size || empty ? "activities" : "route");
  if (empty) openImporter();

  document.getElementById("show-tracks")!.addEventListener("change", (e) => activities?.setVisible((e.target as HTMLInputElement).checked));

  const center = planner.startPoint ?? activities?.homeCenter();
  if (center) map.jumpTo({ center, zoom: 13 });
});

// --- collapsible panel; the map keeps its center clear of it ---

function setPanel(open: boolean) {
  panel.classList.toggle("closed", !open);
  document.getElementById("panel-toggle")!.hidden = open;
  const wide = window.matchMedia("(min-width: 701px)").matches;
  map.setPadding({ left: open && wide ? panel.offsetWidth + 16 : 0, top: 0, right: 0, bottom: open && !wide ? panel.offsetHeight : 0 });
}
document.getElementById("panel-close")!.addEventListener("click", () => setPanel(false));
document.getElementById("panel-toggle")!.addEventListener("click", () => setPanel(true));
window.addEventListener("resize", () => setPanel(!panel.classList.contains("closed")));
setPanel(true);

// --- phone: swipe the bottom sheet down to fold it ---
// From the header, or from the content once it is scrolled to its top (otherwise the swipe scrolls it).

let drag: { y0: number; t0: number; dy: number; target: HTMLElement; active: boolean } | null = null;

/** Whether something between the touched element and the panel is scrolled down (the swipe is a scroll then). */
function scrolledAbove(el: HTMLElement): boolean {
  for (let e: HTMLElement | null = el; e && e !== panel; e = e.parentElement) if (e.scrollTop > 0) return true;
  return false;
}

panel.addEventListener(
  "touchstart",
  (e) => {
    drag = null;
    const target = e.target as HTMLElement;
    if (e.touches.length !== 1 || window.matchMedia("(min-width: 701px)").matches) return;
    if (target.closest("input, select, textarea")) return; // sliders drag sideways, fields keep their gestures
    drag = { y0: e.touches[0].clientY, t0: e.timeStamp, dy: 0, target, active: false };
  },
  { passive: true },
);
panel.addEventListener(
  "touchmove",
  (e) => {
    if (!drag) return;
    const dy = e.touches[0].clientY - drag.y0;
    if (!drag.active) {
      if (Math.abs(dy) < 8) return;
      if (dy < 0 || scrolledAbove(drag.target)) {
        drag = null;
        return;
      }
      drag.active = true;
      panel.style.transition = "none";
    }
    e.preventDefault(); // the sheet follows the finger, the content does not scroll
    drag.dy = Math.max(0, dy);
    panel.style.transform = `translateY(${drag.dy}px)`;
  },
  { passive: false },
);
function endDrag(e: TouchEvent) {
  const d = drag;
  drag = null;
  if (!d?.active) return;
  panel.style.transition = "";
  panel.style.transform = "";
  const fast = d.dy > 30 && d.dy / Math.max(1, e.timeStamp - d.t0) > 0.5; // a flick, px/ms
  if (fast || d.dy > Math.min(120, panel.offsetHeight * 0.25)) setPanel(false);
}
panel.addEventListener("touchend", endDrag);
panel.addEventListener("touchcancel", endDrag);

// --- background OSM download progress ---

async function pollOsmStatus() {
  const box = document.getElementById("osm-status")!;
  try {
    const s = await fetchRoutingStatus();
    const done = s.tiles_cached >= s.tiles_total;
    box.hidden = done && !s.error;
    document.getElementById("osm-status-text")!.textContent = s.error
      ? `Préparation des chemins interrompue (${s.error}) : les zones manquantes seront téléchargées à la demande.`
      : `Préparation des chemins de vos zones de course : ${s.tiles_cached}/${s.tiles_total}`;
    (document.getElementById("osm-status-bar") as HTMLElement).style.width = `${(100 * s.tiles_cached) / Math.max(s.tiles_total, 1)}%`;
    if (!done && s.running) setTimeout(pollOsmStatus, 3000);
  } catch {
    box.hidden = true;
  }
}
