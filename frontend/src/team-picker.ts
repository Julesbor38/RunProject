/** Choosing the 3 familiers of a team (team trail, 3 against 3 friendly battles): hatched ones only. */
import { apiFetch } from "./api";
import { escape } from "./format";
import { petArt } from "./pet-art";

interface Pet {
  id: number;
  name: string;
  species: string;
  form: string;
  type: string;
  type_name: string;
  color: string;
  active: boolean;
  stage: { index: number; name: string };
  level: number;
  branch: string | null;
}

const SIZE = 3;

export async function pickTeam(title: string): Promise<number[] | null> {
  const r = await apiFetch("/api/game");
  if (!r.ok) return null;
  const pets = ((await r.json()).pets as Pet[]).filter((p) => p.stage.index > 0);
  if (pets.length < SIZE) {
    alert(`Il faut ${SIZE} familiers éclos pour une équipe (tu en as ${pets.length}). Adopte, achète ou fais éclore les autres.`);
    return null;
  }
  // the strongest first, the active one in
  const chosen = new Set(pets.slice().sort((a, b) => Number(b.active) - Number(a.active) || b.stage.index - a.stage.index || b.level - a.level)
    .slice(0, SIZE).map((p) => p.id));
  const box = document.createElement("div");
  box.className = "team-picker";
  document.body.appendChild(box);
  return new Promise((resolve) => {
    const done = (v: number[] | null) => {
      box.remove();
      resolve(v);
    };
    const draw = () => {
      box.innerHTML = `<div class="team-card"><h2>${escape(title)}</h2><p class="muted small">Choisis ${SIZE} familiers (${chosen.size}/${SIZE}).</p>
        <div class="team-list">${pets.map((p) => `<button type="button" class="team-pet ${chosen.has(p.id) ? "on" : ""}" data-id="${p.id}">
          ${petArt({ species: p.species, stage: p.stage.index, branch: p.branch, color: p.color, type: p.type }, 64)}
          <strong>${escape(p.name)}</strong><span class="muted small">${escape(p.form)} · niv. ${p.level}</span>
          <span class="type-badge t-${p.type}">${escape(p.type_name)}</span></button>`).join("")}</div>
        <div class="team-buttons"><button type="button" class="primary go" ${chosen.size === SIZE ? "" : "disabled"}>C'est parti</button>
          <button type="button" class="text-btn cancel">Annuler</button></div></div>`;
      box.querySelectorAll<HTMLButtonElement>(".team-pet").forEach((b) =>
        b.addEventListener("click", () => {
          const id = Number(b.dataset.id);
          if (chosen.has(id)) chosen.delete(id);
          else if (chosen.size < SIZE) chosen.add(id);
          draw();
        }),
      );
      box.querySelector(".go")!.addEventListener("click", () => done([...chosen]));
      box.querySelector(".cancel")!.addEventListener("click", () => done(null));
    };
    draw();
  });
}
