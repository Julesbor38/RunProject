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
  const { body, aura, ground, defs = "", rays } = draw(id, o);
  return `<svg class="pet-svg" viewBox="0 0 200 200" width="${size}" height="${size}" role="img" aria-hidden="true">
    <defs>
      <radialGradient id="${id}-shade" cx="35%" cy="28%" r="80%"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></radialGradient>
      ${aura ? `<radialGradient id="${id}-aura" r="50%"><stop offset=".45" stop-color="${aura}" stop-opacity=".55"/><stop offset="1" stop-color="${aura}" stop-opacity="0"/></radialGradient>` : ""}
      <filter id="${id}-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      ${defs}
    </defs>
    ${rays ? raysOf(rays) : ""}
    ${aura ? `<circle cx="100" cy="112" r="92" fill="url(#${id}-aura)"/>` : ""}
    <ellipse cx="100" cy="186" rx="${ground}" ry="7" fill="#000" opacity=".14"/>
    ${body}
  </svg>`;
}

/** body; aura: glow colour behind; ground: shadow width; defs: gradients of its own; rays: a legendary halo. */
type Drawing = { body: string; aura?: string; ground: number; defs?: string; rays?: string };

function raysOf(color: string): string {
  const rays = Array.from({ length: 16 }, (_, i) => {
    const a = (i * Math.PI) / 8;
    const w = i % 2 ? 0.06 : 0.1;
    const p = (r: number, da: number) => `${(100 + r * Math.cos(a + da)).toFixed(1)},${(108 + r * Math.sin(a + da)).toFixed(1)}`;
    return `<polygon points="${p(30, -w)} ${p(98, 0)} ${p(30, w)}" fill="${color}" opacity="${i % 2 ? 0.35 : 0.6}"/>`;
  });
  return `<g class="pet-rays">${rays.join("")}</g>`;
}
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

// --- shop species: bigger, stronger, more elaborate ---

const GOLD_RAYS = "#ffd166";

function dragonWing(side: number, x: number, y: number, span: number, h: number, bone: string, skin: string): string {
  // a bat-like wing: bones from the shoulder, membranes between, scalloped edge
  const s = side;
  const tip = [x + s * span, y - h];
  const f1 = [x + s * span * 0.95, y + h * 0.15];
  const f2 = [x + s * span * 0.62, y + h * 0.42];
  const f3 = [x + s * span * 0.3, y + h * 0.55];
  return `<path d="M${x} ${y}L${tip[0]} ${tip[1]}Q${f1[0] + s * 4} ${(tip[1] + f1[1]) / 2} ${f1[0]} ${f1[1]}Q${(f1[0] + f2[0]) / 2} ${f1[1] - h * 0.02} ${f2[0]} ${f2[1]}Q${(f2[0] + f3[0]) / 2} ${f2[1] - h * 0.04} ${f3[0]} ${f3[1]}Q${x + s * 6} ${y + h * 0.3} ${x} ${y + h * 0.2}z" fill="${skin}"/>
    <path d="M${x} ${y}L${tip[0]} ${tip[1]}M${x + s * span * 0.25} ${y - h * 0.25}L${f1[0]} ${f1[1]}M${x + s * span * 0.2} ${y - h * 0.18}L${f2[0]} ${f2[1]}M${x + s * span * 0.12} ${y - h * 0.1}L${f3[0]} ${f3[1]}" stroke="${bone}" stroke-width="4" stroke-linecap="round" fill="none"/>`;
}

function horn(x: number, y: number, len: number, curl: number, color: string, w = 7): string {
  return `<path d="M${x - w} ${y}Q${x - w * 0.3 + curl * 0.3} ${y - len * 0.6} ${x + curl} ${y - len}Q${x + w * 0.4 + curl * 0.2} ${y - len * 0.5} ${x + w} ${y}z" fill="${color}"/>`;
}

// Brasaltor: a basalt dragon with lava veins
const BASALT = "#3b2a2a";
const BASALT_D = "#241818";
const LAVA = "#ff6a1a";
const LAVA_HOT = "#ffd23f";

const brasaltor: Draw = (id, o) => {
  const defs = `<linearGradient id="${id}-lava" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${LAVA_HOT}"/><stop offset="1" stop-color="${LAVA}"/></linearGradient>`;
  const veins = (cx: number, cy: number, r: number) =>
    `<path d="M${cx - r * 0.6} ${cy - r * 0.1}l${r * 0.2} ${r * 0.15}l-${r * 0.05} ${r * 0.25}M${cx + r * 0.55} ${cy - r * 0.3}l-${r * 0.18} ${r * 0.2}l${r * 0.1} ${r * 0.2}M${cx + r * 0.3} ${cy + r * 0.5}l${r * 0.15} ${r * 0.18}" stroke="url(#${id}-lava)" stroke-width="3" fill="none" stroke-linecap="round" filter="url(#${id}-glow)"/>`;
  if (o.stage === 0)
    return { ground: 38, defs, aura: "#ff6a1a", body: `${blob(id, path("M100 38c-31 0-52 43-52 82 0 33 23 62 52 62s52-29 52-62c0-39-21-82-52-82z"), BASALT)}
      <path d="M78 70l14 18-8 14 16 16-6 20M126 96l-12 14 10 12-8 18" stroke="url(#${id}-lava)" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round" filter="url(#${id}-glow)"/>
      <circle cx="112" cy="62" r="3" fill="${LAVA_HOT}"/>` };
  const st = o.stage;
  const r = [0, 42, 50, 58, 62][st];
  const cy = 182 - r * 0.95;
  const parts: string[] = [];
  if (st >= 2) parts.push(dragonWing(-1, 100 - r * 0.55, cy - r * 0.35, [0, 0, 40, 54, 62][st], [0, 0, 40, 62, 84][st], BASALT_D, st >= 3 ? "#5a2a1a" : "#4a3030"),
                          dragonWing(1, 100 + r * 0.55, cy - r * 0.35, [0, 0, 40, 54, 62][st], [0, 0, 40, 62, 84][st], BASALT_D, st >= 3 ? "#5a2a1a" : "#4a3030"));
  if (st === 1) parts.push(`<path d="M${100 - r * 0.8} ${cy - r * 0.2}l-12 -14 4 18zM${100 + r * 0.8} ${cy - r * 0.2}l12 -14 -4 18z" fill="${BASALT_D}"/>`);
  // tail with a flame
  parts.push(`<path d="M${100 + r * 0.6} ${cy + r * 0.6}Q${100 + r * 1.5} ${cy + r * 0.7} ${100 + r * 1.45} ${cy - r * 0.1}l-6 10Q${100 + r * 1.2} ${cy + r * 0.45} ${100 + r * 0.6} ${cy + r * 0.3}z" fill="${BASALT_D}"/>
    <path d="M${100 + r * 1.45} ${cy - r * 0.1}q-10 -14 2 -30q2 12 10 14q-2 10 -12 16z" fill="url(#${id}-lava)" filter="url(#${id}-glow)"/>`);
  // horns
  const hl = [0, 14, 24, 34, 46][st];
  parts.push(horn(100 - r * 0.45, cy - r * 0.75, hl, -hl * 0.5, st >= 3 ? "#1a1010" : BASALT_D, 6 + st), horn(100 + r * 0.45, cy - r * 0.75, hl, hl * 0.5, st >= 3 ? "#1a1010" : BASALT_D, 6 + st));
  if (st >= 3) parts.push(horn(100 - r * 0.15, cy - r * 0.92, hl * 0.6, -4, LAVA, 4), horn(100 + r * 0.15, cy - r * 0.92, hl * 0.6, 4, LAVA, 4));
  // back spikes, glowing
  if (st >= 3) for (const [dx, h] of [[-0.85, 16], [-0.95, 12], [0.85, 16], [0.95, 12]] as const)
    parts.push(`<path d="M${100 + dx * r} ${cy - r * 0.1}l${dx < 0 ? -h : h} -4 ${dx < 0 ? 6 : -6} 12z" fill="url(#${id}-lava)"/>`);
  // legs, body, belly plates
  parts.push(`${ell(100 - r * 0.5, cy + r * 0.92, r * 0.32, r * 0.16).replace("/>", ` fill="${BASALT_D}"/>`)}${ell(100 + r * 0.5, cy + r * 0.92, r * 0.32, r * 0.16).replace("/>", ` fill="${BASALT_D}"/>`)}
    ${blob(id, ell(100, cy, r, r * 0.95), BASALT)}
    <path d="M${100 - r * 0.45} ${cy + r * 0.05}Q100 ${cy + r * 1.1} ${100 + r * 0.45} ${cy + r * 0.05}Q100 ${cy + r * 0.25} ${100 - r * 0.45} ${cy + r * 0.05}z" fill="url(#${id}-lava)" opacity="${st >= 3 ? 1 : 0.85}"/>
    <path d="M${100 - r * 0.3} ${cy + r * 0.32}h${r * 0.6}M${100 - r * 0.25} ${cy + r * 0.52}h${r * 0.5}M${100 - r * 0.16} ${cy + r * 0.7}h${r * 0.32}" stroke="${LAVA}" stroke-width="2.5" opacity=".7"/>
    ${veins(100, cy, r)}`);
  // face
  const ey = cy - r * 0.32;
  parts.push(st >= 3 ? eyes(100, ey, r * 0.34, 9, "glow", LAVA_HOT) : eyes(100, ey, r * 0.34, st === 1 ? 9.5 : 9, st === 1 ? "cute" : "bold"));
  if (st < 3) parts.push(blush(100, ey + 14, r * 0.55, 6));
  parts.push(`<circle cx="${100 - 6}" cy="${ey + 13}" r="2" fill="${LAVA}"/><circle cx="${100 + 6}" cy="${ey + 13}" r="2" fill="${LAVA}"/>`, mouth(100, ey + 21, st >= 3 ? 11 : 8, st >= 3 ? "grin" : st === 2 ? "fang" : "smile"));
  if (st === 4) {
    parts.push(`<path d="M${100 - r * 0.9} ${cy - r * 0.95}q-6-18 6-26q0 12 8 14M${100 + r * 0.9} ${cy - r * 0.95}q6-18-6-26q0 12-8 14" stroke="${LAVA_HOT}" stroke-width="3" fill="none" filter="url(#${id}-glow)"/>
      <circle cx="30" cy="40" r="3" fill="${LAVA_HOT}"/><circle cx="168" cy="30" r="2.5" fill="${LAVA}"/><circle cx="182" cy="96" r="2" fill="${LAVA_HOT}"/><circle cx="16" cy="104" r="2.5" fill="${LAVA}"/>
      ${sparkle(40, 24, 6, LAVA_HOT)}${sparkle(160, 16, 5, "#fff", 0.6)}`);
  }
  return { ground: r + 10, defs, aura: st >= 3 ? "#ff6a1a" : undefined, rays: st === 4 ? GOLD_RAYS : undefined, body: parts.join("") };
};

// Aurorelle: a celestial fox with aurora tails (1, 3, 6, then 9)
const NIGHT_FUR = "#2b2f6b";

const aurorelle: Draw = (id, o) => {
  const defs = `<linearGradient id="${id}-aurora" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#5ef2c4"/><stop offset=".5" stop-color="#7b6cff"/><stop offset="1" stop-color="#ff8ad8"/></linearGradient>`;
  if (o.stage === 0)
    return { ground: 36, defs, aura: "#7b6cff", body: `${blob(id, path("M100 40c-30 0-50 42-50 80 0 32 22 60 50 60s50-28 50-60c0-38-20-80-50-80z"), NIGHT_FUR)}
      <path d="M52 118q24-26 48-6t48-8l0 14q-24 14-48 6t-48 10z" fill="url(#${id}-aurora)" opacity=".9"/>
      ${star(80, 80, 5, "#fff")}${star(122, 70, 3, "#ffe37a")}${star(110, 150, 4, "#fff")}${star(84, 156, 2.5, "#ffe37a")}` };
  const st = o.stage;
  const r = [0, 40, 48, 54, 58][st];
  const cy = 182 - r * 0.95;
  const n = [0, 1, 3, 6, 9][st];
  const parts: string[] = [];
  if (st === 4) parts.push(`<circle cx="100" cy="${cy - r * 0.55}" r="${r * 0.95}" fill="none" stroke="#ffe37a" stroke-width="3" opacity=".8" filter="url(#${id}-glow)"/>`);
  // tails in a fan behind
  for (let i = 0; i < n; i++) {
    const a = n === 1 ? 55 : -80 + (160 * i) / (n - 1);
    const len = r * [0, 1.5, 1.7, 1.85, 2.0][st];
    const w = r * 0.42;
    const oy = cy + r * 0.3; // they start low behind the body and rise above it
    parts.push(`<g transform="rotate(${a} 100 ${oy})"><path d="M${100 - r * 0.14} ${oy}C${100 - w} ${oy - len * 0.45} ${100 - w * 0.9} ${oy - len * 0.85} 100 ${oy - len}C${100 + w * 0.9} ${oy - len * 0.85} ${100 + w} ${oy - len * 0.45} ${100 + r * 0.14} ${oy}z" fill="url(#${id}-aurora)" stroke="#fff" stroke-opacity=".35" stroke-width="1.5"/>
      <path d="M100 ${oy - len * 0.25}Q${100 + w * 0.25} ${oy - len * 0.6} 100 ${oy - len * 0.92}" stroke="#fff" stroke-width="2" opacity=".5" fill="none"/>
      ${star(100, oy - len * 0.86, 4, "#fff")}</g>`);
  }
  parts.push(foxEars(100, cy - r * 1.2, r * 0.62, r * 0.9, NIGHT_FUR, "url(#" + id + "-aurora)", st >= 3));
  parts.push(`${ell(100 - r * 0.4, cy + r * 0.92, r * 0.26, r * 0.14).replace("/>", ` fill="#1a1d48"/>`)}${ell(100 + r * 0.4, cy + r * 0.92, r * 0.26, r * 0.14).replace("/>", ` fill="#1a1d48"/>`)}
    ${blob(id, ell(100, cy, r, r * 0.97), NIGHT_FUR)}
    <path d="M${100 - r * 0.72} ${cy + r * 0.1}q${r * 0.72} ${r * 0.85} ${r * 1.44} 0q-${r * 0.12} ${r * 0.72} -${r * 0.72} ${r * 0.8}q-${r * 0.6} -${r * 0.08} -${r * 0.72} -${r * 0.8}z" fill="#d9dcff"/>
    ${star(100 - r * 0.55, cy - r * 0.3, 2.2, "#fff")}${star(100 + r * 0.6, cy + r * 0.2, 2.5, "#ffe37a")}${star(100 - r * 0.2, cy + r * 0.75, 2, "#fff")}`);
  // forehead mark: star, then crescent, then a gem
  const fy = cy - r * 0.62;
  parts.push(st === 1 ? star(100, fy, 5, "#ffe37a") : `<path d="M96 ${fy - 7}a8 8 0 1 0 10 10a6 6 0 1 1-10-10z" fill="#ffe37a" filter="url(#${id}-glow)"/>`);
  if (st >= 3) parts.push(`<path d="M100 ${cy + r * 0.45}l7 9-7 9-7-9z" fill="#5ef2c4" stroke="#fff" stroke-width="1.5" filter="url(#${id}-glow)"/>`);
  const ey = cy - r * 0.2;
  parts.push(st >= 3 ? eyes(100, ey, r * 0.36, 9, "glow", "#9ff7ff") : eyes(100, ey, r * 0.36, 9.5, st === 1 ? "cute" : "bold"));
  if (st < 3) parts.push(blush(100, ey + 14, r * 0.58, 6));
  parts.push(`<ellipse cx="100" cy="${ey + 14}" rx="4.5" ry="3.2" fill="${INK}"/>`, mouth(100, ey + 19, 8, st >= 3 ? "fang" : "smile"));
  if (st === 4) {
    parts.push(`${star(100, cy - r * 1.62, 7, "#ffe37a")}${star(100 - r * 0.6, cy - r * 1.45, 4.5, "#fff")}${star(100 + r * 0.6, cy - r * 1.45, 4.5, "#fff")}
      <path d="M${100 - r * 0.6} ${cy - r * 1.45}L100 ${cy - r * 1.62}L${100 + r * 0.6} ${cy - r * 1.45}" stroke="#fff" stroke-width="1" opacity=".6"/>
      ${sparkle(24, 36, 6, "#9ff7ff")}${sparkle(178, 50, 5, "#ff8ad8", 0.5)}${sparkle(184, 150, 4, "#fff", 1)}${sparkle(18, 150, 5, "#ffe37a", 0.3)}`);
  }
  return { ground: r + 8, defs, aura: st >= 2 ? "#7b6cff" : undefined, rays: st === 4 ? GOLD_RAYS : undefined, body: parts.join("") };
};

// Tempestor: a storm dragon with cloud wings
const SKY = "#2a7fd4";
const SKY_D = "#1b5aa0";
const BOLT = "#ffe14d";

function cloud(cx: number, cy: number, w: number, color = "#f2f7ff"): string {
  return `<g fill="${color}"><circle cx="${cx - w * 0.35}" cy="${cy}" r="${w * 0.28}"/><circle cx="${cx}" cy="${cy - w * 0.12}" r="${w * 0.36}"/><circle cx="${cx + w * 0.38}" cy="${cy + 2}" r="${w * 0.26}"/><rect x="${cx - w * 0.6}" y="${cy}" width="${w * 1.2}" height="${w * 0.28}" rx="${w * 0.14}"/></g>`;
}

const bolt = (x: number, y: number, h: number, id: string) =>
  `<path d="M${x} ${y}l${-h * 0.22} ${h * 0.5}h${h * 0.18}l${-h * 0.12} ${h * 0.5}l${h * 0.36} ${-h * 0.62}h${-h * 0.18}l${h * 0.12} ${-h * 0.38}z" fill="${BOLT}" filter="url(#${id}-glow)"/>`;

const tempestor: Draw = (id, o) => {
  if (o.stage === 0)
    return { ground: 36, aura: "#7fc4ff", body: `${blob(id, path("M100 40c-30 0-50 42-50 80 0 32 22 60 50 60s50-28 50-60c0-38-20-80-50-80z"), SKY)}
      ${cloud(86, 92, 34)}${cloud(118, 140, 28)}${bolt(104, 98, 40, id)}` };
  const st = o.stage;
  const r = [0, 40, 48, 56, 60][st];
  const cy = 182 - r * 0.95;
  const parts: string[] = [];
  if (st >= 2) {
    const span = [0, 0, 40, 52, 60][st], h = [0, 0, 36, 58, 78][st];
    parts.push(dragonWing(-1, 100 - r * 0.5, cy - r * 0.3, span, h, "#dff0ff", SKY_D), dragonWing(1, 100 + r * 0.5, cy - r * 0.3, span, h, "#dff0ff", SKY_D));
    parts.push(cloud(100 - r * 0.55 - span * 0.7, cy - r * 0.3 + h * 0.3, 26), cloud(100 + r * 0.55 + span * 0.7, cy - r * 0.3 + h * 0.3, 26));
    if (st >= 3) parts.push(bolt(100 - r * 0.5 - span * 0.6, cy - r * 0.3 + h * 0.35, 30, id), bolt(100 + r * 0.5 + span * 0.62, cy - r * 0.3 + h * 0.35, 30, id));
  }
  // tornado tail
  parts.push(`<path d="M${100 + r * 0.6} ${cy + r * 0.5}q${r * 0.7} 0 ${r * 0.9} ${-r * 0.5}q${r * 0.1} ${-r * 0.3} ${r * 0.35} ${-r * 0.4}" stroke="${SKY_D}" stroke-width="${r * 0.22}" fill="none" stroke-linecap="round"/>
    <path d="M${100 + r * 1.5} ${cy - r * 0.6}q14 4 10 16q-10 -2 -18 6q2 -12 8 -22z" fill="#f2f7ff"/>`);
  // cloud mane and horns (bolts from the adult stage)
  parts.push(cloud(100, cy - r * 0.85, r * 0.9));
  if (st >= 3) parts.push(bolt(100 - r * 0.42, cy - r * 1.55, r * 0.7, id), bolt(100 + r * 0.5, cy - r * 1.55, r * 0.7, id));
  else parts.push(horn(100 - r * 0.4, cy - r * 0.8, 12 + st * 4, -6, "#dff0ff", 5), horn(100 + r * 0.4, cy - r * 0.8, 12 + st * 4, 6, "#dff0ff", 5));
  parts.push(`${ell(100 - r * 0.45, cy + r * 0.92, r * 0.28, r * 0.15).replace("/>", ` fill="${SKY_D}"/>`)}${ell(100 + r * 0.45, cy + r * 0.92, r * 0.28, r * 0.15).replace("/>", ` fill="${SKY_D}"/>`)}
    ${blob(id, ell(100, cy, r, r * 0.95), SKY)}
    <path d="M${100 - r * 0.55} ${cy + r * 0.1}q${r * 0.55} ${r * 0.85} ${r * 1.1} 0q-${r * 0.1} ${r * 0.7} -${r * 0.55} ${r * 0.78}q-${r * 0.45} -${r * 0.08} -${r * 0.55} -${r * 0.78}z" fill="#dff0ff"/>
    ${cloud(100, cy - r * 0.78, r * 0.75)}`);
  const ey = cy - r * 0.18;
  parts.push(st >= 3 ? eyes(100, ey, r * 0.35, 9, "glow", "#e8fbff") : eyes(100, ey, r * 0.35, 9.5, st === 1 ? "cute" : "bold"));
  if (st < 3) parts.push(blush(100, ey + 14, r * 0.58, 6));
  parts.push(mouth(100, ey + 18, st >= 3 ? 11 : 8, st >= 3 ? "grin" : st === 2 ? "fang" : "o"));
  if (st === 4) parts.push(`<path d="M30 30l-6 14M44 20l-6 14M166 28l-6 14M180 40l-6 14M20 120l-6 14M186 120l-6 14" stroke="#9fd3ff" stroke-width="2.5" stroke-linecap="round"/>${bolt(26, 60, 36, id)}${bolt(176, 70, 30, id)}`);
  return { ground: r + 10, aura: st >= 3 ? "#7fc4ff" : undefined, body: parts.join("") };
};

// Sylvarion: a forest stag with crystal antlers in bloom
const MOSS_FUR = "#5aa05a";
const MOSS_D = "#3c7a40";

function antler(side: number, x: number, y: number, size: number, wood: string, tip: string, flowers: boolean, id: string): string {
  const s = side;
  const p = (dx: number, dy: number) => `${x + s * dx * size} ${y - dy * size}`;
  return `<path d="M${p(0, 0)}C${p(0.1, 0.4)} ${p(0.35, 0.6)} ${p(0.4, 1)}M${p(0.15, 0.45)}L${p(0.6, 0.62)}M${p(0.3, 0.75)}L${p(0.75, 1.0)}M${p(0.38, 0.9)}L${p(0.2, 1.25)}" stroke="${wood}" stroke-width="${3 + size * 0.06}" stroke-linecap="round" fill="none"/>
    ${[p(0.4, 1), p(0.6, 0.62), p(0.75, 1.0), p(0.2, 1.25)].map((q) => {
      const [qx, qy] = q.split(" ").map(Number);
      return `<path d="M${qx} ${qy - 7}l4 7-4 7-4-7z" fill="${tip}" filter="url(#${id}-glow)"/>${flowers ? `<circle cx="${qx + s * 4}" cy="${qy + 6}" r="3.5" fill="#ffb3d1"/><circle cx="${qx + s * 4}" cy="${qy + 6}" r="1.4" fill="#fff6a8"/>` : ""}`;
    }).join("")}`;
}

const sylvarion: Draw = (id, o) => {
  if (o.stage === 0)
    return { ground: 36, aura: "#9be89b", body: `${blob(id, path("M100 40c-30 0-50 42-50 80 0 32 22 60 50 60s50-28 50-60c0-38-20-80-50-80z"), MOSS_FUR)}
      <circle cx="80" cy="96" r="7" fill="#fff" opacity=".7"/><circle cx="118" cy="128" r="9" fill="#fff" opacity=".6"/><circle cx="96" cy="150" r="5" fill="#fff" opacity=".6"/>
      <circle cx="122" cy="74" r="5" fill="#ffb3d1"/><circle cx="122" cy="74" r="2" fill="#fff6a8"/><path d="M90 46q10-12 22-2q-10 6-22 2z" fill="${MOSS_D}"/>` };
  const st = o.stage;
  const r = [0, 38, 46, 54, 58][st];
  const cy = 182 - r * 0.95;
  const parts: string[] = [];
  const head = cy - r * 0.78;
  if (st >= 2) {
    const size = [0, 0, 30, 48, 64][st];
    const tip = st >= 3 ? "#9ff7ff" : "#c8e6a0";
    parts.push(antler(-1, 100 - r * 0.28, head, size, "#8a6a45", tip, st >= 3, id), antler(1, 100 + r * 0.28, head, size, "#8a6a45", tip, st >= 3, id));
  } else parts.push(`<path d="M100 ${head - 2}q-2-12 8-16q-1 10-8 16z" fill="${MOSS_D}"/>`);
  // long ears
  parts.push([-1, 1].map((s) => `<ellipse cx="${100 + s * r * 0.78}" cy="${head + 6}" rx="${r * 0.32}" ry="${r * 0.14}" transform="rotate(${s * 25} ${100 + s * r * 0.78} ${head + 6})" fill="${MOSS_FUR}"/>
    <ellipse cx="${100 + s * r * 0.8}" cy="${head + 6}" rx="${r * 0.2}" ry="${r * 0.07}" transform="rotate(${s * 25} ${100 + s * r * 0.8} ${head + 6})" fill="#f7d7c4"/>`).join(""));
  parts.push(`${ell(100 - r * 0.4, cy + r * 0.92, r * 0.18, r * 0.14).replace("/>", ` fill="#4a3a2a"/>`)}${ell(100 + r * 0.4, cy + r * 0.92, r * 0.18, r * 0.14).replace("/>", ` fill="#4a3a2a"/>`)}
    ${blob(id, ell(100, cy, r, r * 0.95), MOSS_FUR)}
    <ellipse cx="100" cy="${cy + r * 0.3}" rx="${r * 0.5}" ry="${r * 0.5}" fill="#f4ecd2" opacity=".9"/>
    ${st <= 2 ? [[-0.55, -0.1], [0.6, 0.05], [-0.4, 0.45], [0.5, 0.5]].map(([dx, dy]) => `<circle cx="${100 + dx * r}" cy="${cy + dy * r}" r="${r * 0.07}" fill="#fff" opacity=".8"/>`).join("") : ""}`);
  if (st >= 3) parts.push(`<path d="M${100 - r * 0.8} ${cy - r * 0.35}Q100 ${cy + r * 0.1} ${100 + r * 0.8} ${cy - r * 0.35}" stroke="${MOSS_D}" stroke-width="6" fill="none"/>
    ${[-0.6, -0.3, 0, 0.3, 0.6].map((dx, i) => `<circle cx="${100 + dx * r}" cy="${cy - r * 0.2 + Math.abs(dx) * -r * 0.2 + (i % 2) * 3}" r="5" fill="${["#ffb3d1", "#fff6a8", "#ffffff", "#ffb3d1", "#fff6a8"][i]}"/>`).join("")}`);
  if (st === 4) parts.push(`<path d="M100 ${cy + r * 0.15}l8 10-8 10-8-10z" fill="#9ff7ff" filter="url(#${id}-glow)"/>
    <path d="M${100 - r * 0.62} ${cy + r * 0.3}l6 -6m-12 0l6 6M${100 + r * 0.62} ${cy + r * 0.3}l6 -6m-12 0l6 6" stroke="#d4ff9a" stroke-width="2.5" filter="url(#${id}-glow)"/>`);
  const ey = cy - r * 0.32;
  parts.push(st >= 3 ? eyes(100, ey, r * 0.34, 8.5, "glow", "#d4ff9a") : eyes(100, ey, r * 0.34, 9.5, st === 1 ? "cute" : "bold"));
  if (st < 4) parts.push(blush(100, ey + 13, r * 0.55, 5.5));
  parts.push(`<ellipse cx="100" cy="${ey + 13}" rx="4" ry="3" fill="${INK}"/>`, mouth(100, ey + 18, 7, st >= 3 ? "fang" : "smile"));
  if (st === 4) {
    const petal = (x: number, y: number, a: number) => `<ellipse cx="${x}" cy="${y}" rx="5" ry="2.6" transform="rotate(${a} ${x} ${y})" fill="#ffb3d1" opacity=".9"/>`;
    parts.push(`${petal(24, 60, 30)}${petal(176, 84, -20)}${petal(16, 140, 70)}${petal(186, 150, 10)}${petal(40, 24, -40)}${sparkle(160, 24, 5, "#d4ff9a")}${sparkle(30, 100, 4, "#fff", 0.6)}`);
  }
  return { ground: r + 6, aura: st >= 3 ? "#9be89b" : undefined, body: parts.join("") };
};

// Colossaure: a frost mammoth titan
const WOOL = "#8a5a3c";
const WOOL_D = "#6a4029";
const FROST = "#cdefff";

const colossaure: Draw = (id, o) => {
  if (o.stage === 0)
    return { ground: 36, body: `${blob(id, path("M100 40c-30 0-50 42-50 80 0 32 22 60 50 60s50-28 50-60c0-38-20-80-50-80z"), WOOL)}
      <path d="M58 82q42-30 84 0q-8-26-42-34q-34 8-42 34z" fill="${FROST}"/><path d="M70 120l6 6m0-6l-6 6M124 140l6 6m0-6l-6 6M100 100l4 4m0-4l-4 4" stroke="#fff" stroke-width="2.5"/>` };
  const st = o.stage;
  const r = [0, 40, 50, 58, 64][st]; // the body; the head is in front of it
  const by = 176 - r * 0.85; // body centre
  const R = r * 0.7; // head
  const hy = by - r * 0.18;
  const HEAD = "#a8714c";
  const parts: string[] = [];
  // frost crystals along the back from the adult stage
  if (st >= 3) for (const [dx, h] of [[-0.75, 18], [-0.4, 28], [0, 34], [0.4, 28], [0.75, 18]] as const)
    parts.push(crystal(100 + dx * r, by - r * 0.62 + Math.abs(dx) * r * 0.2, h + (st === 4 ? 12 : 0), 8, dx * 35, FROST, st === 4 ? ` filter="url(#${id}-glow)"` : ""));
  // legs like pillars, the woolly body, its frost cape
  parts.push([-0.7, -0.35, 0.35, 0.7].map((dx) => `<rect x="${100 + dx * r - r * 0.14}" y="${by + r * 0.35}" width="${r * 0.28}" height="${r * 0.52}" rx="${r * 0.1}" fill="${WOOL_D}"/>
    <rect x="${100 + dx * r - r * 0.15}" y="${by + r * 0.78}" width="${r * 0.3}" height="${r * 0.1}" rx="${r * 0.05}" fill="#4a2c1c"/>`).join(""));
  parts.push(`${blob(id, ell(100, by, r * 1.12, r * 0.78), WOOL_D)}
    <path d="M${100 - r * 1.05} ${by - r * 0.1}Q100 ${by - r * 1.05} ${100 + r * 1.05} ${by - r * 0.1}Q100 ${by - r * 0.55} ${100 - r * 1.05} ${by - r * 0.1}z" fill="${FROST}" opacity="${st >= 2 ? 0.9 : 0.55}"/>`);
  // big ears behind the head
  parts.push([-1, 1].map((s) => `${blob(id, ell(100 + s * R * 1.0, hy + R * 0.05, R * 0.55, R * 0.7), WOOL)}<ellipse cx="${100 + s * R * 1.03}" cy="${hy + R * 0.08}" rx="${R * 0.3}" ry="${R * 0.42}" fill="#d9a07a"/>`).join(""));
  // head, with a tuft of hair
  parts.push(`${blob(id, ell(100, hy, R, R * 0.95), HEAD)}
    <path d="M${100 - R * 0.45} ${hy - R * 0.8}q${R * 0.15} ${-R * 0.5} ${R * 0.3} ${-R * 0.05}q${R * 0.1} ${-R * 0.55} ${R * 0.3} 0q${R * 0.2} ${-R * 0.45} ${R * 0.3} ${R * 0.1}z" fill="${WOOL_D}"/>
    ${st >= 2 ? `<path d="M${100 - R * 0.6} ${hy - R * 0.62}Q100 ${hy - R * 1.05} ${100 + R * 0.6} ${hy - R * 0.62}Q100 ${hy - R * 0.82} ${100 - R * 0.6} ${hy - R * 0.62}z" fill="${FROST}"/>` : ""}`);
  // tusks, curling out and up, from beside the trunk
  const tusk = [0, 16, 26, 36, 46][st];
  parts.push([-1, 1].map((s) => `<path d="M${100 + s * R * 0.3} ${hy + R * 0.42}C${100 + s * (R * 0.4 + tusk * 0.4)} ${hy + R * 0.42 + tusk * 0.7} ${100 + s * (R * 0.5 + tusk)} ${hy + R * 0.3 + tusk * 0.4} ${100 + s * (R * 0.55 + tusk * 0.95)} ${hy + R * 0.1 - tusk * 0.15}C${100 + s * (R * 0.42 + tusk * 0.75)} ${hy + R * 0.38 + tusk * 0.2} ${100 + s * (R * 0.35 + tusk * 0.3)} ${hy + R * 0.48 + tusk * 0.3} ${100 + s * R * 0.12} ${hy + R * 0.5}z" fill="#fff8e8" stroke="#d8c8a8" stroke-width="1.5"/>
    ${st === 4 ? `<path d="M${100 + s * (R * 0.42 + tusk * 0.55)} ${hy + R * 0.6 + tusk * 0.22}l${s * 5} ${-6}" stroke="#ffd166" stroke-width="6" stroke-linecap="round"/>` : ""}`).join(""));
  // trunk, curled at the end
  parts.push(`<path d="M${100 - R * 0.2} ${hy + R * 0.15}C${100 - R * 0.26} ${hy + R * 0.9} ${100 - R * 0.1} ${hy + R * 1.45} ${100 + R * 0.25} ${hy + R * 1.38}C${100 + R * 0.45} ${hy + R * 1.32} ${100 + R * 0.42} ${hy + R * 1.08} ${100 + R * 0.24} ${hy + R * 1.1}C${100 + R * 0.1} ${hy + R * 1.12} ${100 + R * 0.06} ${hy + R * 0.8} ${100 + R * 0.2} ${hy + R * 0.15}z" fill="${HEAD}" stroke="${WOOL_D}" stroke-width="1.5"/>
    <path d="M${100 - R * 0.14} ${hy + R * 0.5}h${R * 0.28}M${100 - R * 0.14} ${hy + R * 0.72}h${R * 0.26}M${100 - R * 0.12} ${hy + R * 0.94}h${R * 0.22}" stroke="${WOOL_D}" stroke-width="2" stroke-linecap="round"/>`);
  const ey = hy - R * 0.18;
  parts.push(st >= 3 ? eyes(100, ey, R * 0.42, 8, "glow", "#bdf4ff") : eyes(100, ey, R * 0.42, 8.5, st === 1 ? "cute" : "bold"));
  if (st < 3) parts.push(blush(100, ey + 13, R * 0.62, 5.5));
  if (st === 4) parts.push(`${["M30 40", "M172 36", "M18 130", "M186 120"].map((m, i) => `<path d="${m}m-6 0h12m-6-6v12m-4-10l8 8m0-8l-8 8" stroke="#9fdcff" stroke-width="2" opacity="${0.9 - i * 0.1}"/>`).join("")}`);
  return { ground: r + 18, aura: st >= 3 ? "#bdf4ff" : undefined, body: parts.join("") };
};

const SPECIES: Record<string, Draw> = { galet, fusette, foulon, brasaltor, aurorelle, tempestor, sylvarion, colossaure };
