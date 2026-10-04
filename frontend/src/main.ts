import { Map, NavigationControl, ScaleControl, GeolocateControl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { ActivitiesView } from "./activities";
import { fetchActivities, fetchFrequency, fetchRoutingStatus } from "./api";
import { Planner } from "./planner";
import { addTerrain } from "./terrain";

type Tab = "route" | "activities";

const panel = document.getElementById("panel")!;
const summary = document.getElementById("summary")!;

const map = new Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  center: [4.8357, 45.764],
  zoom: 11,
});
if (import.meta.env.DEV) Object.assign(window, { map }); // handy from the browser console
map.addControl(new NavigationControl(), "top-right");
map.addControl(new GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");
map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");

const data = fetchActivities();
const frequency = fetchFrequency().catch(() => null); // optional: tracks by sport without it

map.on("load", async () => {
  addTerrain(map);
  let activities: ActivitiesView | null = null;
  try {
    activities = new ActivitiesView(map, await data, (text) => (summary.textContent = text), await frequency);
  } catch (e) {
    summary.textContent = `API injoignable (${(e as Error).message}) : le backend tourne-t-il sur :8000 ?`;
  }
  const planner = new Planner(map, (shown) => activities?.setMuted(shown));

  const showTab = (tab: Tab) => {
    document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.getElementById("tab-route")!.hidden = tab !== "route";
    document.getElementById("tab-activities")!.hidden = tab !== "activities";
    planner.setActive(tab === "route");
    if (activities) activities.interactive = tab === "activities";
  };
  document.querySelectorAll<HTMLButtonElement>(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab as Tab)));
  showTab("route");

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
pollOsmStatus();
