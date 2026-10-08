/**
 * Illustrations of the familiers, drawn in SVG (provisional, until real artwork): one evolution line per
 * species and a distinct look for each final form (branch). Kawaii (big glossy eyes, blush, round shapes)
 * that grows badass with the stages (brows, fangs, armour, auras). Only `petArt()` is used by the app; an
 * unknown species gets a generic creature in its type's colours.
 */

export interface ArtOf {
  species: string;
  stage: number; // 0 egg … 4 final
  branch?: string | null;
  color: string;
  type: string;
}

const TYPE_ACCENT: Record<string, string> = {
  montagne: "#6b5a45",
  vitesse: "#ffb020",
  endurance: "#1b5a43",
  nocturne: "#4b3f8f",
  exploration: "#3f9b4f",
};

const INK = "#1b1f2a";
let uid = 0;

export function petArt(o: ArtOf, size = 160): string {
  const id = `pa${++uid}`;
  const draw = SPECIES[o.species] ?? generic;
  const { body, aura, ground } = draw(id, o);
  return `<svg class="pet-svg" viewBox="0 0 200 200" width="${size}" height="${size}" role="img" aria-hidden="true">
    <defs>
      <radialGradient id="${id}-shade" cx="35%" cy="28%" r="80%"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></radialGradient>
      ${aura ? `<radialGradient id="${id}-aura" r="50%"><stop offset=".45" stop-color="${aura}" stop-opacity=".55"/><stop offset="1" stop-color="${aura}" stop-opacity="0"/></radialGradient>` : ""}
      <filter id="${id}-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    ${aura ? `<circle cx="100" cy="112" r="92" fill="url(#${id}-aura)"/>` : ""}
    <ellipse cx="100" cy="186" rx="${ground}" ry="7" fill="#000" opacity=".14"/>
    ${body}
  </svg>`;
}

type Drawing = { body: string; aura?: string; ground: number };
type Draw = (id: string, o: ArtOf) => Drawing;

// --- shared pieces ---

/** A shape filled with its colour, then the glossy shading on top. */
const blob = (id: string, shape: string, color: string, extra = "") =>
  `${shape.replace("/>", ` fill="${color}" ${extra}/>`)}${shape.replace("/>", ` fill="url(#${id}-shade)"/>`)}`;
const ell = (cx: number, cy: number, rx: number, ry: number) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"/>`;
const path = (d: string) => `<path d="${d}"/>`;

type Mood = "cute" | "bold" | "fierce" | "glow";

/** Two big eyes: cute (round, glossy), bold (a brow), fierce (half-lidded, angry brows), glow (luminous). */
function eyes(cx: number, cy: number, dx: number, r: number, mood: Mood, glow = "#ffe066"): string {
  let out = "";
  for (const side of [-1, 1]) {
    const x = cx + side * dx;
    if (mood === "glow") {
      out += `<ellipse cx="${x}" cy="${cy}" rx="${r * 1.35}" ry="${r * 1.1}" fill="${glow}" opacity=".3"/>
        <ellipse cx="${x}" cy="${cy}" rx="${r}" ry="${r * 0.8}" fill="${glow}"/><ellipse cx="${x}" cy="${cy}" rx="${r * 0.3}" ry="${r * 0.62}" fill="#fff" opacity=".9"/>`;
    } else {
      out += `<ellipse cx="${x}" cy="${cy}" rx="${r}" ry="${r * 1.12}" fill="${INK}"/>
        <ellipse cx="${x}" cy="${cy + r * 0.45}" rx="${r * 0.62}" ry="${r * 0.38}" fill="#6d7cff" opacity=".45"/>
        <circle cx="${x + r * 0.32}" cy="${cy - r * 0.38}" r="${r * 0.4}" fill="#fff"/><circle cx="${x - r * 0.38}" cy="${cy + r * 0.3}" r="${r * 0.17}" fill="#fff"/>`;
    }
    if (mood === "fierce" || mood === "glow") {
      // an angry brow, slanted towards the nose
      out += `<path d="M${x + side * r * 1.25} ${cy - r * 1.55}L${x - side * r * 1.15} ${cy - r * 0.95}" stroke="${INK}" stroke-width="${r * 0.42}" stroke-linecap="round"/>`;
    } else if (mood === "bold") {
      out += `<path d="M${x - r * 0.9} ${cy - r * 1.55}Q${x} ${cy - r * 1.95} ${x + r * 0.9} ${cy - r * 1.55}" stroke="${INK}" stroke-width="${r * 0.3}" fill="none" stroke-linecap="round"/>`;
    }
  }
  return out;
}

function blush(cx: number, cy: number, dx: number, r: number): string {
  return [-1, 1].map((s) => `<ellipse cx="${cx + s * dx}" cy="${cy}" rx="${r}" ry="${r * 0.55}" fill="#ff7b9a" opacity=".5"/>`).join("");
}

/** smile (kawaii), fang (one fang), grin (two fangs, badass), o (surprised). */
function mouth(cx: number, cy: number, w: number, kind: "smile" | "fang" | "grin" | "o"): string {
  if (kind === "o") return `<ellipse cx="${cx}" cy="${cy + 2}" rx="${w * 0.35}" ry="${w * 0.45}" fill="${INK}"/>`;
  if (kind === "grin")
    return `<path d="M${cx - w} ${cy - 1}Q${cx} ${cy + w * 0.9} ${cx + w} ${cy - 1}z" fill="${INK}"/>
      <path d="M${cx - w * 0.7} ${cy}l${w * 0.22} ${w * 0.5}l${w * 0.22} ${-w * 0.45}zM${cx + w * 0.7} ${cy}l${-w * 0.22} ${w * 0.5}l${-w * 0.22} ${-w * 0.45}z" fill="#fff"/>`;
  const smile = `<path d="M${cx - w * 0.6} ${cy}q${w * 0.3} ${w * 0.45} ${w * 0.6} 0q${w * 0.3} ${w * 0.45} ${w * 0.6} 0" stroke="${INK}" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  return kind === "fang" ? smile + `<path d="M${cx + w * 0.22} ${cy + w * 0.12}l${w * 0.14} ${w * 0.42}l${w * 0.14} ${-w * 0.36}z" fill="#fff" stroke="${INK}" stroke-width="1"/>` : smile;
}

function sparkle(x: number, y: number, s: number, color = "#ffd84d", delay = 0): string {
  return `<path class="pet-spark" style="animation-delay:${delay}s" d="M${x} ${y - s}Q${x + s * 0.18} ${y - s * 0.18} ${x + s} ${y}Q${x + s * 0.18} ${y + s * 0.18} ${x} ${y + s}Q${x - s * 0.18} ${y + s * 0.18} ${x - s} ${y}Q${x - s * 0.18} ${y - s * 0.18} ${x} ${y - s}z" fill="${color}"/>`;
}

function star(x: number, y: number, r: number, color: string): string {
  const pts = Array.from({ length: 10 }, (_, i) => {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.45 : r;
    return `${(x + rr * Math.cos(a)).toFixed(1)},${(y + rr * Math.sin(a)).toFixed(1)}`;
  });
  return `<polygon points="${pts.join(" ")}" fill="${color}"/>`;
}

function egg(id: string, base: string, marks: string): Drawing {
  const shape = path("M100 40c-30 0-50 42-50 80 0 32 22 60 50 60s50-28 50-60c0-38-20-80-50-80z");
  return { ground: 36, body: `${blob(id, shape, base)}${marks}<path d="M68 70q14-14 22-8" stroke="#fff" stroke-width="5" opacity=".5" fill="none" stroke-linecap="round"/>` };
}

// --- Galet: a pebble that becomes a mountain ---

const STONE = "#9a8a73";
const STONE_D = "#6e604d";
const MOSS = "#5f9b4c";
const CRYSTAL = "#7fd6e8";

function crystal(x: number, y: number, h: number, w: number, tilt: number, color = CRYSTAL, glow = ""): string {
  return `<g transform="rotate(${tilt} ${x} ${y})"${glow}><path d="M${x} ${y - h}L${x + w} ${y - h * 0.35}L${x + w * 0.6} ${y}L${x - w * 0.6} ${y}L${x - w} ${y - h * 0.35}z" fill="${color}"/>
    <path d="M${x} ${y - h}L${x + w * 0.25} ${y - h * 0.35}L${x} ${y}z" fill="#fff" opacity=".45"/></g>`;
}

const galet: Draw = (id, o) => {
  if (o.stage === 0)
    return egg(id, STONE, `<path d="M80 92l12 10-6 12 10 8M118 128l-8 10 8 10" stroke="${STONE_D}" stroke-width="3" fill="none" stroke-linecap="round"/>
      <path d="M86 46q14-10 28 0q-6 8-14 6q-8 2-14-6z" fill="${MOSS}"/>`);
  if (o.stage === 1)
    return {
      ground: 40,
      body: `${ell(80, 172, 13, 7).replace("/>", ` fill="${STONE_D}"/>`)}${ell(120, 172, 13, 7).replace("/>", ` fill="${STONE_D}"/>`)}
        ${blob(id, ell(100, 138, 46, 40), STONE)}
        <path d="M92 100q-4-14 6-18q2 10-6 18zM104 99q4-16 16-14q-4 12-16 14z" fill="${MOSS}"/>
        <circle cx="76" cy="150" r="4" fill="${STONE_D}" opacity=".5"/><circle cx="126" cy="122" r="3" fill="${STONE_D}" opacity=".5"/>
        ${eyes(100, 134, 17, 9, "cute")}${blush(100, 150, 27, 7)}${mouth(100, 150, 8, "smile")}`,
    };
  if (o.stage === 2)
    return {
      ground: 50,
      body: `${crystal(80, 88, 30, 9, -18)}${crystal(118, 84, 38, 10, 14)}
        ${ell(78, 174, 15, 8).replace("/>", ` fill="${STONE_D}"/>`)}${ell(122, 174, 15, 8).replace("/>", ` fill="${STONE_D}"/>`)}
        ${blob(id, ell(56, 140, 12, 16), STONE_D)}${blob(id, ell(144, 140, 12, 16), STONE_D)}
        ${blob(id, ell(100, 132, 50, 46), STONE)}
        <path d="M70 116l10 6M126 150l8-6l4 8" stroke="${STONE_D}" stroke-width="3" fill="none" stroke-linecap="round"/>
        <path d="M60 108q-2-10 8-12q0 8-8 12z" fill="${MOSS}"/>
        ${eyes(100, 128, 18, 9, "bold")}${blush(100, 146, 30, 7)}${mouth(100, 146, 9, "fang")}`,
    };
  if (o.stage === 3)
    return {
      ground: 60,
      body: `${crystal(72, 78, 40, 11, -24)}${crystal(128, 78, 44, 12, 22)}${crystal(100, 70, 24, 8, 0, "#a6e8f2")}
        ${ell(74, 176, 18, 9).replace("/>", ` fill="${STONE_D}"/>`)}${ell(126, 176, 18, 9).replace("/>", ` fill="${STONE_D}"/>`)}
        ${blob(id, ell(100, 128, 58, 52), STONE)}
        ${blob(id, ell(46, 112, 24, 21), STONE_D)}${blob(id, ell(154, 112, 24, 21), STONE_D)}
        ${blob(id, ell(50, 150, 14, 13), STONE_D)}${blob(id, ell(150, 150, 14, 13), STONE_D)}
        <path d="M100 140l-6 12l8 6l-4 12" stroke="${CRYSTAL}" stroke-width="3.5" fill="none" stroke-linecap="round" filter="url(#${id}-glow)"/>
        ${eyes(100, 120, 19, 9, "fierce")}${mouth(100, 138, 10, "grin")}`,
    };
  if (o.branch === "ombrecrete") {
    const OBS = "#3d3570";
    return {
      aura: "#7b5cff",
      ground: 64,
      body: `<path d="M58 110L14 70l12 34L4 108l30 20zM142 110l44-40-12 34 22 4-30 20z" fill="#2a2450"/>
        ${crystal(70, 74, 46, 12, -26, "#b48cff", ` filter="url(#${id}-glow)"`)}${crystal(130, 74, 46, 12, 26, "#b48cff", ` filter="url(#${id}-glow)"`)}
        <path d="M96 34a16 16 0 1 0 18 20a12 12 0 1 1-18-20z" fill="#ffe37a" filter="url(#${id}-glow)"/>
        ${ell(72, 178, 19, 9).replace("/>", ` fill="#2a2450"/>`)}${ell(128, 178, 19, 9).replace("/>", ` fill="#2a2450"/>`)}
        ${blob(id, ell(100, 126, 60, 56), OBS)}
        ${blob(id, ell(44, 118, 22, 20), "#2a2450")}${blob(id, ell(156, 118, 22, 20), "#2a2450")}
        ${star(76, 150, 4, "#ffe37a")}${star(128, 158, 3, "#fff")}${star(116, 100, 2.5, "#fff")}${star(84, 98, 2, "#ffe37a")}
        ${eyes(100, 120, 20, 10, "glow", "#ffe37a")}${mouth(100, 140, 11, "grin")}
        ${sparkle(26, 40, 7, "#ffe37a")}${sparkle(176, 44, 6, "#fff", 0.5)}${sparkle(182, 140, 5, "#b48cff", 1)}`,
    };
  }
  // Cimeval: the mountain itself
  return {
    aura: "#8fe3ff",
    ground: 66,
    body: `<path d="M50 96L76 40l14 24 10-30 12 28 14-22 26 56z" fill="${STONE_D}"/>
      <path d="M76 40l8 14-8 2-6-4zM100 34l7 16-8 2-6-4zM126 40l7 12-7 3-6-4z" fill="#fff"/>
      ${ell(70, 178, 20, 10).replace("/>", ` fill="${STONE_D}"/>`)}${ell(130, 178, 20, 10).replace("/>", ` fill="${STONE_D}"/>`)}
      ${blob(id, ell(100, 128, 62, 56), STONE)}
      ${blob(id, ell(42, 112, 26, 23), STONE_D)}${blob(id, ell(158, 112, 26, 23), STONE_D)}
      <path d="M30 100l10-8 10 8M150 100l10-8 10 8" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round" opacity=".8"/>
      ${blob(id, ell(56, 160, 18, 16), STONE_D)}${blob(id, ell(144, 160, 18, 16), STONE_D)}
      ${crystal(100, 168, 26, 12, 0, CRYSTAL, ` filter="url(#${id}-glow)"`)}
      ${eyes(100, 118, 20, 10, "fierce")}<path d="M128 104l-8 18" stroke="${STONE_D}" stroke-width="3" stroke-linecap="round"/>
      ${mouth(100, 138, 11, "grin")}
      <circle cx="20" cy="150" r="7" fill="${STONE_D}"/><circle cx="182" cy="84" r="6" fill="${STONE_D}"/><circle cx="176" cy="160" r="4" fill="${STONE}"/>
      ${sparkle(30, 60, 6, "#8fe3ff")}${sparkle(172, 56, 7, "#fff", 0.6)}`,
  };
};

// --- Fusette: a fox kit that becomes lightning, or a shooting star ---

const FOX = "#ef7a2e";
const CREAM = "#fff1dc";

function foxEars(cx: number, top: number, w: number, h: number, fur: string, inner: string, tuft = false): string {
  return [-1, 1]
    .map((s) => {
      const x = cx + s * w;
      return `<path d="M${x - s * w * 0.55} ${top + h * 0.75}L${x + s * w * 0.35} ${top - h * 0.25}L${x + s * w * 0.45} ${top + h * 0.85}z" fill="${fur}"/>
        <path d="M${x - s * w * 0.2} ${top + h * 0.7}L${x + s * w * 0.3} ${top + h * 0.05}L${x + s * w * 0.32} ${top + h * 0.75}z" fill="${inner}"/>
        ${tuft ? `<path d="M${x + s * w * 0.35} ${top - h * 0.25}l${s * 6} ${-8}l${-s * 2} ${10}" fill="${fur}"/>` : ""}`;
    })
    .join("");
}

function foxTail(x: number, y: number, len: number, fur: string, tip: string): string {
  return `<path d="M${x} ${y}q${len * 0.9} ${-len * 0.1} ${len} ${-len * 0.95}q${-len * 0.05} ${len * 0.75} ${-len * 0.7} ${len * 1.05}z" fill="${fur}"/>
    <path d="M${x + len} ${y - len * 0.95}q${-len * 0.05} ${len * 0.4} ${-len * 0.3} ${len * 0.55}q${len * 0.05} ${-len * 0.35} ${len * 0.3} ${-len * 0.55}z" fill="${tip}" stroke="${tip}" stroke-width="${len * 0.12}" stroke-linejoin="round"/>`;
}

function scarf(cx: number, cy: number, w: number, color: string, flow: number): string {
  return `<path d="M${cx - w} ${cy - 4}Q${cx} ${cy + 8} ${cx + w} ${cy - 4}L${cx + w} ${cy + 6}Q${cx} ${cy + 18} ${cx - w} ${cy + 6}z" fill="${color}"/>
    <path d="M${cx + w * 0.55} ${cy + 6}q${flow * 0.4} ${4} ${flow} ${-4}l${-flow * 0.15} ${14}q${-flow * 0.5} ${4} ${-flow * 0.85} ${-2}z" fill="${color}"/>`;
}

const fusette: Draw = (id, o) => {
  if (o.stage === 0)
    return egg(id, FOX, `<path d="M70 96l20 14-12 10 24 18-8 12" stroke="#ffd84d" stroke-width="6" fill="none" stroke-linejoin="round" stroke-linecap="round"/>
      <path d="M100 150q20 10 36-4q-4 24-36 28q-24-2-34-18q14 6 34-6z" fill="${CREAM}" opacity=".8"/>`);
  const s = o.stage;
  if (s === 1)
    return {
      ground: 40,
      body: `${foxTail(124, 168, 34, FOX, "#fff")}${foxEars(100, 84, 26, 34, FOX, CREAM)}
        ${ell(84, 174, 10, 6).replace("/>", ` fill="#7a3a12"/>`)}${ell(116, 174, 10, 6).replace("/>", ` fill="#7a3a12"/>`)}
        ${blob(id, ell(100, 138, 44, 40), FOX)}
        <path d="M70 146q30 34 60 0q-6 26-30 28q-24-2-30-28z" fill="${CREAM}"/>
        ${eyes(100, 132, 17, 9.5, "cute")}${blush(100, 150, 28, 7)}<ellipse cx="100" cy="148" rx="4" ry="3" fill="${INK}"/>${mouth(100, 153, 7, "smile")}`,
    };
  if (s === 2)
    return {
      ground: 50,
      body: `${foxTail(126, 166, 46, FOX, "#fff")}${foxEars(100, 72, 30, 42, FOX, CREAM)}
        ${ell(80, 176, 12, 7).replace("/>", ` fill="#7a3a12"/>`)}${ell(120, 176, 12, 7).replace("/>", ` fill="#7a3a12"/>`)}
        ${blob(id, ell(100, 132, 48, 46), FOX)}
        <path d="M66 140q34 38 68 0q-6 30-34 32q-28-2-34-32z" fill="${CREAM}"/>
        ${scarf(100, 160, 30, "#d6324a", -34)}
        ${eyes(100, 126, 18, 9, "bold")}${blush(100, 144, 30, 6)}<ellipse cx="100" cy="142" rx="4.5" ry="3.2" fill="${INK}"/>${mouth(100, 147, 8, "fang")}`,
    };
  if (s === 3)
    return {
      ground: 58,
      body: `<path d="M26 120h30M18 136h34M30 152h24" stroke="#ffd84d" stroke-width="4" stroke-linecap="round" opacity=".8"/>
        ${foxTail(130, 168, 54, FOX, "#fff")}${foxEars(100, 58, 32, 50, FOX, CREAM, true)}
        ${ell(78, 178, 14, 8).replace("/>", ` fill="#7a3a12"/>`)}${ell(122, 178, 14, 8).replace("/>", ` fill="#7a3a12"/>`)}
        ${blob(id, ell(100, 128, 52, 52), FOX)}
        <path d="M60 134q40 44 80 0q-6 36-40 38q-34-2-40-38z" fill="${CREAM}"/>
        <path d="M58 112l-14-6 12 14zM142 112l14-6-12 14z" fill="${FOX}"/>
        ${scarf(100, 160, 34, "#d6324a", -52)}
        ${eyes(100, 120, 19, 9, "fierce")}<ellipse cx="100" cy="138" rx="5" ry="3.4" fill="${INK}"/>${mouth(100, 145, 9, "grin")}`,
    };
  if (o.branch === "nuitfilante") {
    const NIGHT = "#2f3a86";
    return {
      aura: "#6f7dff",
      ground: 60,
      body: `<path d="M128 166C170 160 190 120 196 70C180 110 160 128 132 140z" fill="${NIGHT}"/>
        <path d="M150 150C178 136 192 106 196 70" stroke="#9fb0ff" stroke-width="3" fill="none" opacity=".7"/>
        ${star(194, 66, 13, "#ffe37a")}${sparkle(176, 98, 5, "#fff")}${sparkle(184, 128, 4, "#ffe37a", 0.5)}
        ${foxEars(100, 54, 32, 52, NIGHT, "#9fb0ff", true)}
        ${ell(78, 178, 14, 8).replace("/>", ` fill="#1a2052"/>`)}${ell(122, 178, 14, 8).replace("/>", ` fill="#1a2052"/>`)}
        ${blob(id, ell(100, 128, 54, 54), NIGHT)}
        <path d="M60 134q40 44 80 0q-6 36-40 38q-34-2-40-38z" fill="#c9d2ff"/>
        <path d="M96 84a10 10 0 1 0 12 12a8 8 0 1 1-12-12z" fill="#ffe37a" filter="url(#${id}-glow)"/>
        ${star(70, 112, 2.5, "#fff")}${star(132, 104, 2, "#fff")}${star(140, 150, 2.5, "#ffe37a")}
        ${eyes(100, 120, 20, 9.5, "glow", "#ffe37a")}<ellipse cx="100" cy="139" rx="5" ry="3.4" fill="${INK}"/>${mouth(100, 146, 9, "grin")}
        ${sparkle(28, 50, 6, "#ffe37a")}${sparkle(20, 140, 5, "#fff", 0.8)}`,
    };
  }
  // Éclairon: lightning fox
  const GOLD = "#ffb627";
  return {
    aura: "#ffd84d",
    ground: 62,
    body: `<path d="M130 164l26-34-12-2 28-44-8 34 14 2-38 50z" fill="#ffe14d" stroke="#e08a00" stroke-width="3" stroke-linejoin="round" filter="url(#${id}-glow)"/>
      <path d="M50 96l-22-20 26 6-10-24 22 18 2-26 14 26M150 96l22-20-26 6 10-24-22 18-2-26-14 26" fill="${GOLD}"/>
      ${foxEars(100, 50, 34, 54, GOLD, "#fff4c2", true)}
      ${ell(76, 178, 15, 8).replace("/>", ` fill="#8a4a00"/>`)}${ell(124, 178, 15, 8).replace("/>", ` fill="#8a4a00"/>`)}
      ${blob(id, ell(100, 128, 55, 54), GOLD)}
      <path d="M60 134q40 44 80 0q-6 36-40 38q-34-2-40-38z" fill="#fff4c2"/>
      <path d="M60 92q40-16 80 0" stroke="${INK}" stroke-width="6" fill="none"/>
      <circle cx="84" cy="90" r="10" fill="#7fe8ff" stroke="${INK}" stroke-width="4"/><circle cx="116" cy="90" r="10" fill="#7fe8ff" stroke="${INK}" stroke-width="4"/>
      <path d="M80 86l6 4M112 86l6 4" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
      <path d="M64 150l8-6-2 10 8-4" stroke="#e08a00" stroke-width="2.5" fill="none"/>
      ${eyes(100, 122, 20, 9, "fierce")}<ellipse cx="100" cy="139" rx="5" ry="3.4" fill="${INK}"/>${mouth(100, 146, 10, "grin")}
      <path d="M24 120l10 6-8 4 12 8M176 150l-10 4 8 4-12 6" stroke="#ffe14d" stroke-width="3" fill="none" stroke-linejoin="round" filter="url(#${id}-glow)"/>
      ${sparkle(30, 40, 7, "#fff")}${sparkle(170, 30, 6, "#ffe14d", 0.4)}`,
  };
};

// --- Foulon: a cub that becomes an ultra-runner, or a wandering guardian ---

const FUR = "#2f8a5f";
const FUR_D = "#1f6545";
const MUZZLE = "#d9f0e0";

function bearEars(cx: number, top: number, dx: number, r: number, fur: string, inner: string): string {
  return [-1, 1].map((s) => `<circle cx="${cx + s * dx}" cy="${top}" r="${r}" fill="${fur}"/><circle cx="${cx + s * dx}" cy="${top}" r="${r * 0.55}" fill="${inner}"/>`).join("");
}

function headband(cx: number, cy: number, w: number, color: string, tails: number): string {
  return `<path d="M${cx - w} ${cy + 2}Q${cx} ${cy - 12} ${cx + w} ${cy + 2}l0 10Q${cx} ${cy - 2} ${cx - w} ${cy + 12}z" fill="${color}"/>
    ${tails ? `<path d="M${cx + w - 4} ${cy + 6}q${tails * 0.5} ${-6} ${tails} ${-2}l-4 9q${-tails * 0.5} ${-2} ${-tails + 4} ${2}zM${cx + w - 4} ${cy + 8}q${tails * 0.45} ${8} ${tails * 0.9} ${12}l-8 4q${-tails * 0.3} ${-6} ${-tails * 0.5} ${-12}z" fill="${color}"/>` : ""}`;
}

const foulon: Draw = (id, o) => {
  if (o.stage === 0)
    return egg(id, FUR, `<path d="M52 112q48 16 96 0l0 14q-48 16-96 0z" fill="#ef7a2e"/><circle cx="84" cy="80" r="6" fill="${MUZZLE}" opacity=".6"/><circle cx="118" cy="150" r="8" fill="${MUZZLE}" opacity=".5"/>`);
  if (o.stage === 1)
    return {
      ground: 42,
      body: `${bearEars(100, 102, 32, 13, FUR, MUZZLE)}
        ${ell(82, 174, 12, 7).replace("/>", ` fill="${FUR_D}"/>`)}${ell(118, 174, 12, 7).replace("/>", ` fill="${FUR_D}"/>`)}
        ${blob(id, ell(100, 138, 46, 40), FUR)}
        ${headband(100, 110, 40, "#ef7a2e", 0)}
        ${ell(100, 150, 18, 12).replace("/>", ` fill="${MUZZLE}"/>`)}
        ${eyes(100, 132, 18, 9, "cute")}${blush(100, 148, 30, 7)}<ellipse cx="100" cy="145" rx="5" ry="3.5" fill="${INK}"/>${mouth(100, 151, 7, "smile")}`,
    };
  if (o.stage === 2)
    return {
      ground: 50,
      body: `${bearEars(100, 92, 36, 15, FUR, MUZZLE)}
        <path d="M68 168h26l2 10H66zM106 168h26l2 10h-30z" fill="#fff"/><path d="M72 172l12-3M110 172l12-3" stroke="#ef7a2e" stroke-width="3" stroke-linecap="round"/>
        ${blob(id, ell(56, 142, 12, 15), FUR_D)}${blob(id, ell(144, 142, 12, 15), FUR_D)}
        ${blob(id, ell(100, 132, 50, 46), FUR)}
        ${headband(100, 102, 44, "#ef7a2e", 30)}
        ${ell(100, 146, 20, 13).replace("/>", ` fill="${MUZZLE}"/>`)}
        ${eyes(100, 126, 19, 9, "bold")}${blush(100, 144, 32, 6)}<ellipse cx="100" cy="141" rx="5.5" ry="3.8" fill="${INK}"/>${mouth(100, 148, 8, "fang")}`,
    };
  if (o.stage === 3)
    return {
      ground: 60,
      body: `${bearEars(100, 82, 40, 17, FUR, MUZZLE)}
        <path d="M64 170h30l2 10H62zM106 170h30l2 10h-34z" fill="#fff"/><path d="M68 174l14-3M110 174l14-3" stroke="#ef7a2e" stroke-width="3" stroke-linecap="round"/>
        ${blob(id, ell(100, 128, 58, 52), FUR)}
        ${blob(id, ell(44, 130, 18, 24), FUR_D)}${blob(id, ell(156, 130, 18, 24), FUR_D)}
        <rect x="80" y="148" width="40" height="24" rx="4" fill="#fff"/><text x="100" y="166" font-family="Barlow Condensed, sans-serif" font-weight="700" font-size="17" text-anchor="middle" fill="${INK}">42</text>
        ${headband(100, 92, 50, "#ef7a2e", 44)}
        ${ell(100, 134, 20, 12).replace("/>", ` fill="${MUZZLE}"/>`)}
        ${eyes(100, 116, 20, 9, "fierce")}<ellipse cx="100" cy="130" rx="6" ry="4" fill="${INK}"/>${mouth(100, 137, 9, "grin")}`,
    };
  if (o.branch === "sentinomade") {
    const LEAF = "#4caf50";
    const leaf = (x: number, y: number, r: number, a: number, c = LEAF) =>
      `<path transform="rotate(${a} ${x} ${y})" d="M${x} ${y - r}q${r * 0.8} ${r * 0.6} 0 ${r * 2}q${-r * 0.8} ${-r * 0.6} 0 ${-r * 2}z" fill="${c}"/>`;
    return {
      aura: "#7fe08a",
      ground: 64,
      body: `<path d="M64 76l-10-26 8 4-2-16 10 14 2-10 6 22M136 76l10-26-8 4 2-16-10 14-2-10-6 22" stroke="#7a5230" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
        ${leaf(54, 40, 7, -30)}${leaf(146, 40, 7, 30)}${leaf(68, 28, 6, 10, "#8bd17c")}${leaf(132, 28, 6, -10, "#8bd17c")}
        ${blob(id, ell(100, 130, 62, 56), FUR)}
        <path d="M44 120Q40 60 100 56Q160 60 156 120Q140 84 100 84Q60 84 44 120z" fill="#2e7d32"/>
        ${leaf(50, 96, 9, -40)}${leaf(150, 96, 9, 40)}${leaf(70, 70, 9, -20, "#66bb6a")}${leaf(130, 70, 9, 20, "#66bb6a")}${leaf(100, 62, 9, 0)}
        ${ell(72, 180, 20, 9).replace("/>", ` fill="${FUR_D}"/>`)}${ell(128, 180, 20, 9).replace("/>", ` fill="${FUR_D}"/>`)}
        <path d="M66 110L88 176M134 110L112 176" stroke="#7a5230" stroke-width="6"/>
        <circle cx="100" cy="160" r="13" fill="#e8c26a" stroke="#7a5230" stroke-width="3"/><path d="M100 150l4 10-4 10-4-10z" fill="#d6324a"/><path d="M100 160l4 10h-8z" fill="#fff"/>
        ${ell(100, 132, 20, 12).replace("/>", ` fill="${MUZZLE}"/>`)}
        ${eyes(100, 114, 21, 9.5, "glow", "#b9ff8a")}<ellipse cx="100" cy="129" rx="6" ry="4" fill="${INK}"/>${mouth(100, 136, 9, "fang")}
        ${leaf(24, 130, 6, 50, "#8bd17c")}${leaf(180, 70, 6, -40)}${leaf(176, 150, 5, 20, "#8bd17c")}
        ${sparkle(30, 70, 5, "#d4ff9a")}${sparkle(172, 110, 5, "#fff", 0.7)}`,
    };
  }
  // Ultravent: the ultra-runner, wind in the headband
  return {
    aura: "#5fe0c8",
    ground: 66,
    body: `<path d="M16 96q20-8 34 4M10 120q24-8 40 6M24 150q14-6 26 2" stroke="#bff6ea" stroke-width="4" fill="none" stroke-linecap="round"/>
      ${bearEars(100, 78, 42, 18, FUR, MUZZLE)}
      <path d="M60 170h32l2 12H58zM108 170h32l2 12h-36z" fill="#fff"/><path d="M64 175l16-4M112 175l16-4" stroke="#ef7a2e" stroke-width="3.5" stroke-linecap="round"/>
      ${blob(id, ell(100, 128, 62, 54), FUR)}
      ${blob(id, ell(40, 128, 20, 26), FUR_D)}${blob(id, ell(160, 128, 20, 26), FUR_D)}
      <path d="M58 104Q100 128 142 104L146 150Q100 168 54 150z" fill="#26323f" opacity=".92"/>
      <rect x="62" y="114" width="14" height="26" rx="6" fill="#4fc3f7"/><rect x="124" y="114" width="14" height="26" rx="6" fill="#4fc3f7"/>
      <rect x="64" y="110" width="10" height="6" rx="2" fill="#1b1f2a"/><rect x="126" y="110" width="10" height="6" rx="2" fill="#1b1f2a"/>
      <path d="M90 150l10 22 10-22" stroke="#d6324a" stroke-width="4" fill="none"/><circle cx="100" cy="174" r="9" fill="#ffd84d" stroke="#e0a800" stroke-width="2.5"/>
      ${headband(100, 86, 54, "#ef7a2e", 70)}
      ${ell(100, 130, 20, 12).replace("/>", ` fill="${MUZZLE}"/>`)}
      ${eyes(100, 110, 21, 9.5, "fierce")}<path d="M72 96l8 14" stroke="${FUR_D}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="100" cy="126" rx="6" ry="4" fill="${INK}"/>${mouth(100, 133, 10, "grin")}
      ${sparkle(176, 40, 6, "#fff")}${sparkle(24, 60, 5, "#bff6ea", 0.5)}`,
  };
};

// --- unknown species: a generic creature in its type's colours ---

const generic: Draw = (id, o) => {
  if (o.stage === 0) return egg(id, o.color, `<circle cx="84" cy="96" r="9" fill="${TYPE_ACCENT[o.type] ?? "#555"}" opacity=".55"/>`);
  const r = [0, 40, 50, 58, 64][o.stage];
  const cy = 178 - r;
  return {
    aura: o.stage === 4 ? TYPE_ACCENT[o.type] : undefined,
    ground: r,
    body: `${blob(id, ell(100, cy, r, r * 0.95), o.color)}
      ${eyes(100, cy - r * 0.15, r * 0.36, 8, o.stage >= 3 ? "fierce" : "cute")}${o.stage < 3 ? blush(100, cy + r * 0.15, r * 0.55, 6) : ""}
      ${mouth(100, cy + r * 0.2, 8, o.stage >= 3 ? "grin" : "smile")}`,
  };
};

const SPECIES: Record<string, Draw> = { galet, fusette, foulon };
