/** Elevation profile: single series, 2px line over a light area, crosshair + tooltip on hover. */

const W = 300;
const H = 110;
const PAD = { top: 10, right: 8, bottom: 20, left: 34 };

export function renderProfile(
  container: HTMLElement,
  profile: [number, number][],
  color: string,
  onHover: (distanceM: number | null) => void,
) {
  container.innerHTML = "";
  if (profile.length < 2) return;
  const total = profile[profile.length - 1][0];
  const zs = profile.map(([, z]) => z);
  // Round the elevation axis to 20 m steps, with at least 60 m of range so flat routes don't look steep.
  let lo = Math.floor(Math.min(...zs) / 20) * 20;
  let hi = Math.ceil(Math.max(...zs) / 20) * 20;
  if (hi - lo < 60) {
    const mid = (hi + lo) / 2;
    lo = Math.floor((mid - 30) / 20) * 20;
    hi = lo + 60;
  }
  const x = (d: number) => PAD.left + (d / total) * (W - PAD.left - PAD.right);
  const y = (z: number) => PAD.top + (1 - (z - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);

  const line = profile.map(([d, z], i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(z).toFixed(1)}`).join("");
  const area = `${line}L${x(total).toFixed(1)},${y(lo)}L${x(0).toFixed(1)},${y(lo)}Z`;
  const ticks = [lo, (lo + hi) / 2, hi];
  const kmTicks = niceKmTicks(total);

  const svg = `
    <svg viewBox="0 0 ${W} ${H}" class="profile-svg" role="img" aria-label="Profil altimétrique : de ${Math.round(Math.min(...zs))} à ${Math.round(Math.max(...zs))} m">
      ${ticks.map((t) => `<line class="grid" x1="${PAD.left}" x2="${W - PAD.right}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${PAD.left - 4}" y="${y(t) + 3}" text-anchor="end">${Math.round(t)}</text>`).join("")}
      ${kmTicks.map((k) => `<text class="axis" x="${x(k * 1000)}" y="${H - 6}" text-anchor="middle">${k} km</text>`).join("")}
      <path d="${area}" fill="${color}" fill-opacity="0.14"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
      <line class="cross" y1="${PAD.top}" y2="${H - PAD.bottom}" visibility="hidden"/>
      <circle class="dot" r="4" fill="${color}" stroke="var(--bg)" stroke-width="2" visibility="hidden"/>
      <rect class="hit" x="${PAD.left}" y="0" width="${W - PAD.left - PAD.right}" height="${H}" fill="transparent"/>
    </svg>
    <div class="profile-tip" hidden></div>`;
  container.innerHTML = svg;

  const el = container.querySelector("svg")!;
  const cross = el.querySelector(".cross") as SVGLineElement;
  const dot = el.querySelector(".dot") as SVGCircleElement;
  const tip = container.querySelector(".profile-tip") as HTMLElement;
  const hit = el.querySelector(".hit") as SVGRectElement;

  const move = (clientX: number) => {
    const box = el.getBoundingClientRect();
    const sx = ((clientX - box.left) / box.width) * W;
    const d = Math.max(0, Math.min(total, ((sx - PAD.left) / (W - PAD.left - PAD.right)) * total));
    const i = Math.min(profile.length - 1, Math.max(0, nearestIndex(profile, d)));
    const [pd, pz] = profile[i];
    for (const node of [cross, dot]) node.setAttribute("visibility", "visible");
    cross.setAttribute("x1", String(x(pd)));
    cross.setAttribute("x2", String(x(pd)));
    dot.setAttribute("cx", String(x(pd)));
    dot.setAttribute("cy", String(y(pz)));
    tip.hidden = false;
    tip.textContent = `${(pd / 1000).toFixed(1).replace(".", ",")} km · ${Math.round(pz)} m`;
    const left = (x(pd) / W) * box.width;
    tip.style.left = `${Math.min(Math.max(left, 40), box.width - 40)}px`;
    onHover(pd);
  };
  const leave = () => {
    for (const node of [cross, dot]) node.setAttribute("visibility", "hidden");
    tip.hidden = true;
    onHover(null);
  };
  hit.addEventListener("pointermove", (e) => move(e.clientX));
  hit.addEventListener("pointerleave", leave);
}

function nearestIndex(profile: [number, number][], d: number) {
  let lo = 0;
  let hi = profile.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (profile[mid][0] < d) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && d - profile[lo - 1][0] < profile[lo][0] - d ? lo - 1 : lo;
}

function niceKmTicks(totalM: number) {
  const km = totalM / 1000;
  const step = km > 30 ? 10 : km > 12 ? 5 : km > 5 ? 2 : 1;
  const out = [];
  for (let k = step; k < km - step * 0.3; k += step) out.push(k);
  return out;
}

/** Point at `distanceM` along a [lon, lat, ...] polyline. */
export function pointAt(coords: number[][], distanceM: number): [number, number] {
  let acc = 0;
  for (let i = 1; i < coords.length; i++) {
    const [lon1, lat1] = coords[i - 1];
    const [lon2, lat2] = coords[i];
    const k = 111_320 * Math.cos((lat1 * Math.PI) / 180);
    const seg = Math.hypot((lon2 - lon1) * k, (lat2 - lat1) * 110_540);
    if (acc + seg >= distanceM) {
      const t = seg ? (distanceM - acc) / seg : 0;
      return [lon1 + t * (lon2 - lon1), lat1 + t * (lat2 - lat1)];
    }
    acc += seg;
  }
  const last = coords[coords.length - 1];
  return [last[0], last[1]];
}
