/**
 * Provisional illustrations of the familiers, drawn in SVG: one silhouette per stage (egg, baby, young,
 * adult, final form), in the species' colour, with the marks of its type (peaks for Montagne, a swoosh for
 * Vitesse, a headband for Endurance, a moon for Nocturne, a sprout for Exploration). To be replaced by real
 * artwork: only `petArt()` is used by the rest of the app.
 */

const TYPE_ACCENT: Record<string, string> = {
  montagne: "#6b5a45",
  vitesse: "#ffb020",
  endurance: "#1b5a43",
  nocturne: "#4b3f8f",
  exploration: "#3f9b4f",
};

let uid = 0;

/** SVG markup of a familier at a stage (0 egg … 4 final), of a type, in a colour. */
export function petArt(color: string, type: string, stage: number, size = 160): string {
  const id = `pet${++uid}`;
  const accent = TYPE_ACCENT[type] ?? "#555";
  const body = stage === 0 ? egg(id, color, accent) : creature(id, color, accent, type, stage);
  return `<svg class="pet-svg" viewBox="0 0 200 200" width="${size}" height="${size}" role="img" aria-hidden="true">
    <defs>
      <radialGradient id="${id}-shade" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".22"/></radialGradient>
      <radialGradient id="${id}-aura" r="50%"><stop offset=".55" stop-color="${accent}" stop-opacity=".35"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></radialGradient>
    </defs>
    <ellipse cx="100" cy="182" rx="${stage === 0 ? 34 : 30 + stage * 9}" ry="7" fill="#000" opacity=".12"/>
    ${body}
  </svg>`;
}

function egg(id: string, color: string, accent: string): string {
  return `<g>
    <path d="M100 38c-30 0-50 42-50 80 0 30 22 58 50 58s50-28 50-58c0-38-20-80-50-80z" fill="${color}"/>
    <circle cx="82" cy="96" r="9" fill="${accent}" opacity=".55"/><circle cx="118" cy="122" r="12" fill="${accent}" opacity=".5"/>
    <circle cx="94" cy="146" r="6" fill="${accent}" opacity=".5"/><circle cx="121" cy="80" r="5" fill="${accent}" opacity=".55"/>
    <path d="M100 38c-30 0-50 42-50 80 0 30 22 58 50 58s50-28 50-58c0-38-20-80-50-80z" fill="url(#${id}-shade)"/>
  </g>`;
}

function creature(id: string, color: string, accent: string, type: string, stage: number): string {
  const r = [0, 40, 50, 58, 64][stage]; // body radius
  const cy = 176 - r - 4;
  const top = cy - r;
  const eyeY = cy - r * 0.15;
  const eyeDx = r * 0.36;
  const eyeR = stage === 1 ? 9 : stage === 2 ? 8 : 7;
  const fierce = stage >= 3;
  const parts: string[] = [];
  if (stage === 4) parts.push(`<circle cx="100" cy="${cy}" r="${r + 30}" fill="url(#${id}-aura)"/>`);
  parts.push(typeBack(type, accent, color, cy, r, top));
  // feet, body, belly
  parts.push(`<ellipse cx="${100 - r * 0.45}" cy="${cy + r * 0.92}" rx="${r * 0.3}" ry="${r * 0.16}" fill="${accent}"/>
    <ellipse cx="${100 + r * 0.45}" cy="${cy + r * 0.92}" rx="${r * 0.3}" ry="${r * 0.16}" fill="${accent}"/>
    <ellipse cx="100" cy="${cy}" rx="${r}" ry="${r * 0.95}" fill="${color}"/>
    ${stage >= 2 ? `<ellipse cx="100" cy="${cy + r * 0.32}" rx="${r * 0.55}" ry="${r * 0.5}" fill="#fff" opacity=".28"/>` : ""}
    ${stage >= 3 ? `<path d="M${100 - r * 0.8} ${cy - r * 0.2}q${r * 0.15} ${r * 0.2} 0 ${r * 0.4}M${100 + r * 0.8} ${cy - r * 0.2}q${-r * 0.15} ${r * 0.2} 0 ${r * 0.4}" stroke="${accent}" stroke-width="5" fill="none" stroke-linecap="round" opacity=".7"/>` : ""}
    <ellipse cx="100" cy="${cy}" rx="${r}" ry="${r * 0.95}" fill="url(#${id}-shade)"/>`);
  // face
  const glow = type === "nocturne" ? "#ffe37a" : "#fff";
  for (const dx of [-eyeDx, eyeDx]) {
    parts.push(`<ellipse cx="${100 + dx}" cy="${eyeY}" rx="${eyeR}" ry="${eyeR * (fierce ? 0.85 : 1.1)}" fill="#1b2420"/>
      <circle cx="${100 + dx + eyeR * 0.35}" cy="${eyeY - eyeR * 0.4}" r="${eyeR * 0.38}" fill="${glow}"/>`);
    if (fierce) parts.push(`<path d="M${100 + dx - eyeR * 1.2} ${eyeY - eyeR * (dx < 0 ? 1.5 : 1.1)}L${100 + dx + eyeR * 1.2} ${eyeY - eyeR * (dx < 0 ? 1.1 : 1.5)}" stroke="#1b2420" stroke-width="3.5" stroke-linecap="round"/>`);
    else parts.push(`<ellipse cx="${100 + dx * 1.35}" cy="${eyeY + eyeR * 1.6}" rx="${eyeR * 0.8}" ry="${eyeR * 0.45}" fill="#ff7b7b" opacity=".45"/>`);
  }
  parts.push(`<path d="M${100 - 6} ${eyeY + eyeR * 1.7}q6 ${fierce ? 3 : 6} 12 0" stroke="#1b2420" stroke-width="3" fill="none" stroke-linecap="round"/>`);
  parts.push(typeFront(type, accent, cy, r, top, stage));
  if (stage === 4) parts.push(sparkles(cy, r));
  return parts.join("");
}

/** Behind the body: ears, horns, tails. */
function typeBack(type: string, accent: string, color: string, cy: number, r: number, top: number): string {
  switch (type) {
    case "montagne": // two rocky peaks on the head
      return `<path d="M${100 - r * 0.75} ${top + r * 0.45}L${100 - r * 0.45} ${top - r * 0.35}L${100 - r * 0.15} ${top + r * 0.3}z" fill="${accent}"/>
        <path d="M${100 + r * 0.15} ${top + r * 0.3}L${100 + r * 0.5} ${top - r * 0.5}L${100 + r * 0.85} ${top + r * 0.45}z" fill="${accent}"/>
        <path d="M${100 + r * 0.38} ${top - r * 0.27}L${100 + r * 0.5} ${top - r * 0.5}L${100 + r * 0.62} ${top - r * 0.27}z" fill="#fff" opacity=".85"/>`;
    case "vitesse": // swept-back pointy ears and a speed tail
      return `<path d="M${100 - r * 0.55} ${top + r * 0.35}L${100 - r * 1.05} ${top - r * 0.3}L${100 - r * 0.15} ${top + r * 0.1}z" fill="${color}"/>
        <path d="M${100 + r * 0.55} ${top + r * 0.35}L${100 + r * 1.05} ${top - r * 0.3}L${100 + r * 0.15} ${top + r * 0.1}z" fill="${color}"/>
        <path d="M${100 + r * 0.8} ${cy + r * 0.3}q${r * 0.6} ${-r * 0.1} ${r * 0.95} ${-r * 0.7}q${-r * 0.1} ${r * 0.55} ${-r * 0.8} ${r * 0.95}z" fill="${accent}"/>`;
    case "endurance": // round, sturdy ears
      return `<circle cx="${100 - r * 0.62}" cy="${top + r * 0.22}" r="${r * 0.3}" fill="${color}"/><circle cx="${100 - r * 0.62}" cy="${top + r * 0.22}" r="${r * 0.15}" fill="${accent}" opacity=".6"/>
        <circle cx="${100 + r * 0.62}" cy="${top + r * 0.22}" r="${r * 0.3}" fill="${color}"/><circle cx="${100 + r * 0.62}" cy="${top + r * 0.22}" r="${r * 0.15}" fill="${accent}" opacity=".6"/>`;
    case "nocturne": // bat-like wings
      return `<path d="M${100 - r * 0.7} ${cy - r * 0.1}q${-r * 0.7} ${-r * 0.6} ${-r * 0.95} ${-r * 0.1}q${r * 0.2} ${r * 0.05} ${r * 0.25} ${r * 0.35}q${r * 0.2} ${-r * 0.1} ${r * 0.35} ${r * 0.2}z" fill="${accent}"/>
        <path d="M${100 + r * 0.7} ${cy - r * 0.1}q${r * 0.7} ${-r * 0.6} ${r * 0.95} ${-r * 0.1}q${-r * 0.2} ${r * 0.05} ${-r * 0.25} ${r * 0.35}q${-r * 0.2} ${-r * 0.1} ${-r * 0.35} ${r * 0.2}z" fill="${accent}"/>`;
    default: // exploration: long ears like a hare's
      return `<ellipse cx="${100 - r * 0.35}" cy="${top - r * 0.05}" rx="${r * 0.16}" ry="${r * 0.45}" fill="${color}" transform="rotate(-15 ${100 - r * 0.35} ${top})"/>
        <ellipse cx="${100 + r * 0.35}" cy="${top - r * 0.05}" rx="${r * 0.16}" ry="${r * 0.45}" fill="${color}" transform="rotate(15 ${100 + r * 0.35} ${top})"/>`;
  }
}

/** In front: headband, moon, sprout. */
function typeFront(type: string, accent: string, cy: number, r: number, top: number, stage: number): string {
  switch (type) {
    case "endurance":
      return stage >= 2 ? `<path d="M${100 - r * 0.93} ${cy - r * 0.5}Q100 ${cy - r * 0.68} ${100 + r * 0.93} ${cy - r * 0.5}" stroke="#e8692c" stroke-width="${r * 0.14}" fill="none" stroke-linecap="round"/>` : "";
    case "nocturne":
      return `<path d="M${100 - 2} ${top - r * 0.05}a${r * 0.22} ${r * 0.22} 0 1 0 ${r * 0.3} ${r * 0.3}a${r * 0.17} ${r * 0.17} 0 1 1 ${-r * 0.3} ${-r * 0.3}z" fill="#ffe37a"/>`;
    case "exploration":
      return `<path d="M100 ${top + 4}q-2 ${-r * 0.3} ${-r * 0.3} ${-r * 0.35}q${r * 0.32} 0 ${r * 0.3} ${r * 0.35}q${r * 0.05} ${-r * 0.32} ${r * 0.35} ${-r * 0.32}q0 ${r * 0.32} ${-r * 0.35} ${r * 0.32}" fill="${accent}"/>`;
    case "vitesse":
      return stage >= 2 ? `<path d="M${100 - r * 1.25} ${cy}h${r * 0.3}M${100 - r * 1.35} ${cy + r * 0.3}h${r * 0.4}M${100 - r * 1.2} ${cy - r * 0.3}h${r * 0.25}" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>` : "";
    default:
      return "";
  }
}

function sparkles(cy: number, r: number): string {
  const pts = [[-1.25, -0.9], [1.2, -1.0], [1.35, 0.4], [-1.4, 0.35]];
  return pts
    .map(([x, y], i) => {
      const cx = 100 + x * r, cyy = cy + y * r, s = i % 2 ? 5 : 7;
      return `<path class="pet-spark" style="animation-delay:${i * 0.4}s" d="M${cx} ${cyy - s}L${cx + s * 0.3} ${cyy - s * 0.3}L${cx + s} ${cyy}L${cx + s * 0.3} ${cyy + s * 0.3}L${cx} ${cyy + s}L${cx - s * 0.3} ${cyy + s * 0.3}L${cx - s} ${cyy}L${cx - s * 0.3} ${cyy - s * 0.3}z" fill="#ffcf4d"/>`;
    })
    .join("");
}
