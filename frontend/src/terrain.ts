import type { IControl, Map } from "maplibre-gl";

// Same open DEM as the backend (AWS Terrarium tiles), so the 3D view matches computed climbs.
const DEM_TILES = ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"];
const EXAGGERATION = 1.4;

/** Hillshading under the roads, plus a 3D terrain toggle. */
export function addTerrain(map: Map) {
  const dem = { type: "raster-dem" as const, tiles: DEM_TILES, tileSize: 256, encoding: "terrarium" as const, maxzoom: 14 };
  // MapLibre advises separate sources for hillshade and terrain.
  map.addSource("hillshade-dem", dem);
  map.addSource("terrain-dem", dem);
  const firstRoad = map.getStyle().layers.find((l) => l.type === "line" || l.type === "symbol")?.id;
  map.addLayer(
    {
      id: "hillshade",
      type: "hillshade",
      source: "hillshade-dem",
      paint: { "hillshade-exaggeration": 0.35, "hillshade-shadow-color": "#3d3d3d", "hillshade-highlight-color": "#ffffff" },
    },
    firstRoad,
  );
  map.addControl(new TerrainControl(), "top-right");
}

class TerrainControl implements IControl {
  private map?: Map;
  private button = document.createElement("button");

  onAdd(map: Map) {
    this.map = map;
    const box = document.createElement("div");
    box.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this.button.type = "button";
    this.button.className = "terrain-toggle";
    this.button.textContent = "3D";
    this.button.title = "Relief en 3D";
    this.button.addEventListener("click", () => this.toggle());
    box.appendChild(this.button);
    return box;
  }

  onRemove() {
    this.button.parentElement?.remove();
  }

  private toggle() {
    const map = this.map!;
    const on = !map.getTerrain();
    map.setTerrain(on ? { source: "terrain-dem", exaggeration: EXAGGERATION } : null);
    map.easeTo({ pitch: on ? 60 : 0, duration: 800 });
    this.button.classList.toggle("on", on);
    this.button.setAttribute("aria-pressed", String(on));
  }
}
