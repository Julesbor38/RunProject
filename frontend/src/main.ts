import { Map, NavigationControl, ScaleControl, GeolocateControl, setWorkerUrl } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { ActivitiesView } from "./activities";
import { fetchActivities, fetchRoutingStatus } from "./api";
import { ensureLoggedIn, signOut } from "./auth";
import { setupImporter, takeNewActivities } from "./importer";
import { Planner } from "./planner";
import { Ratings } from "./ratings";
import { addTerrain } from "./terrain";

// The production bundle doesn't ship MapLibre's sibling worker file: point it at the one Vite bundles.
// (In dev, MapLibre isn't pre-bundled and finds its worker next to itself.)
if (import.meta.env.PROD) setWorkerUrl(maplibreWorkerUrl);

type Tab = "route" | "activities";

const panel = document.getElementById("panel")!;
const summary = document.getElementById("summary")!;

const map = new Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  center: [4.8357, 45.764],
  zoom: 11,
  attributionControl: { compact: true }, // a small ⓘ: keeps the bottom of the map free on phones
});
if (import.meta.env.DEV) Object.assign(window, { map }); // handy from the browser console
map.addControl(new NavigationControl(), "top-right");
map.addControl(new GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");
map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");

// Nothing of the user's data is requested before login (the base map is public).
const loggedIn = ensureLoggedIn();
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
  const planner = new Planner(map, (shown) => activities?.setMuted(shown));

  const showTab = (tab: Tab) => {
    document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.getElementById("tab-route")!.hidden = tab !== "route";
    document.getElementById("tab-activities")!.hidden = tab !== "activities";
    planner.setActive(tab === "route");
    // Tracks open their sheet (and rating) on click in both tabs, unless the planner needs that click.
    if (activities) activities.clickable = (point) => tab === "activities" || !planner.claimsClick(point);
  };
  document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab as Tab)));
  showTab(newKeys.size ? "activities" : "route"); // after an import: straight to the new activities

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
