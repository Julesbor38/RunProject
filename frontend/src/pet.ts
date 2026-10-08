/**
 * « Familier » tab: the three starters to adopt (all of them, each once; they grow each on their own side),
 * a row to switch between my familiers, then the active one. A tap on its picture
 * opens what points buy: levels (+1, +5, as many as possible), and at the stage's max level the evolution
 * (from the adult stage: which final form the running profile leans towards). Everything is decided by the
 * server; this only shows it.
 */
import { apiFetch } from "./api";
import { escape } from "./format";
import { petArt } from "./pet-art";

interface Stats {
  hp: number;
  attack: number;
  defense: number;
  speed: number;
}

interface BranchView {
  id: string;
  name: string;
  type: string;
  type_name: string;
  hint: string;
  score: number;
  leading: boolean;
}

interface PetView {
  id: number;
  name: string;
  species: string;
  form: string;
  type: string;
  type_name: string;
  color: string;
  active: boolean;
  origin: string;
  stage: { index: number; id: string; name: string; max_level: number; final: boolean };
  level: number;
  branch: string | null;
  stats: Stats;
  next_level: { cost: number; cost_5: number; levels_5: number; affordable: number; affordable_cost?: number } | null;
  evolution: { stage: string; level: number; ready: boolean; cost: number; stats: Stats; form: string | null; branches?: BranchView[] } | null;
}

interface Starter {
  id: string;
  type: string;
  type_name: string;
  names: string[];
  color: string;
  description: string;
  base: Stats;
  branches: { id: string; name: string; type: string; hint: string }[];
  adopted: boolean;
}

interface GameState {
  wallet: { points: number; gems: number };
  starter_chosen: boolean;
  pets: PetView[];
}

const STAT_NAMES: [keyof Stats, string][] = [["hp", "PV"], ["attack", "Attaque"], ["defense", "Défense"], ["speed", "Vitesse"]];
const STAT_SCALE = 400; // the bars' full width (about the best final form at level 100)
const nf = (n: number) => n.toLocaleString("fr-FR");

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export class PetTab {
  private state: GameState | null = null;
  private open = false; // the upgrade sheet under the picture
  private busy = false;
  private box = document.getElementById("pet-body")!;

  async refresh() {
    const r = await apiFetch("/api/game");
    if (!r.ok) {
      this.box.innerHTML = `<p class="status error">Familier indisponible (${r.status}).</p>`;
      return;
    }
    this.state = (await r.json()) as GameState;
    const rs = await apiFetch("/api/game/starters");
    this.starters = rs.ok ? ((await rs.json()) as { starters: Starter[] }).starters : [];
    if (!this.state.pets.length) this.renderStarters();
    else this.render();
  }

  private starters: Starter[] = [];

  // --- the starter ---

  private renderStarters() {
    this.box.innerHTML = `
      <h2>Adopte ton premier familier</h2>
      <p class="muted small">Il grandit avec les points que tu gagnes en courant et en explorant. Tu pourras adopter les deux autres
        quand tu voudras : chacun évolue de son côté.</p>
      ${this.starterCards(this.starters)}
      <p id="pet-status" class="status" hidden></p>`;
    this.bindStarters();
  }

  private starterCards(starters: Starter[]): string {
    return `<div class="starters">${starters
        .map(
          (s) => `<article class="starter" data-id="${s.id}">
            <div class="starter-art">${petArt({ species: s.id, stage: 1, color: s.color, type: s.type }, 110)}</div>
            <div class="starter-text"><strong>${escape(s.names[1])}</strong> <span class="type-badge t-${s.type}">${escape(s.type_name)}</span>
              <p class="small">${escape(s.description)}</p>
              ${statBars(s.base, 130)}
              <div class="finals">${s.branches
                .map((b) => `<figure>${petArt({ species: s.id, stage: 4, branch: b.id, color: s.color, type: b.type }, 64)}
                  <figcaption><strong>${escape(b.name)}</strong><span class="muted">${escape(b.hint)}</span></figcaption></figure>`)
                .join("")}</div>
              <button type="button" class="primary choose">Adopter ${escape(s.names[1])}</button></div>
          </article>`,
        )
        .join("")}</div>`;
  }

  private bindStarters() {
    this.box.querySelectorAll<HTMLButtonElement>(".choose").forEach((b) =>
      b.addEventListener("click", () => {
        const s = this.starters.find((x) => x.id === b.closest<HTMLElement>(".starter")!.dataset.id)!;
        this.chooseStarter(s);
      }),
    );
  }

  private async chooseStarter(s: Starter) {
    const name = prompt(`Adopter ${s.names[1]} (${s.type_name}) : quel nom lui donner ?`, s.names[1]);
    if (name === null) return; // cancelled
    const r = await apiFetch("/api/game/starter", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ species: s.id, name: name.trim() || undefined }),
    });
    if (!r.ok) return this.status((await r.json().catch(() => ({}))).detail ?? `erreur ${r.status}`, true);
    this.open = true;
    await this.refresh();
  }

  // --- the active familier ---

  private render() {
    const s = this.state!;
    const pet = s.pets.find((p) => p.active) ?? s.pets[0];
    if (!pet) return;
    const st = pet.stage;
    const levelPct = Math.round((100 * pet.level) / st.max_level);
    const others = this.starters.filter((x) => !x.adopted && !s.pets.some((p) => p.origin === "starter" && p.species === x.id));
    this.box.innerHTML = `
      ${s.pets.length > 1 ? `<div class="pet-switch" role="tablist">${s.pets
        .map((p) => `<button type="button" role="tab" data-id="${p.id}" aria-selected="${p.id === pet.id}">${petArt(art(p), 46)}
          <span>${escape(p.name)}</span><span class="muted">niv. ${p.level}</span></button>`)
        .join("")}</div>` : ""}
      <div class="pet-card t-${pet.type}">
        <div class="pet-head">
          <div><h2 class="pet-name">${escape(pet.name)} <button type="button" class="text-btn rename" title="Renommer">✎</button></h2>
            <span class="muted small">${escape(pet.form)} · ${escape(st.name)}</span></div>
          <span class="type-badge t-${pet.type}">${escape(pet.type_name)}</span>
        </div>
        <button type="button" class="pet-art ${this.open ? "" : "hint"}" aria-expanded="${this.open}" aria-label="Faire progresser ${escape(pet.name)}">
          ${petArt(art(pet), 180)}
        </button>
        <div class="pet-level"><strong>Niv. ${pet.level}</strong><div class="track"><div style="width:${levelPct}%"></div></div>
          <span class="muted small">max ${st.max_level} au stade ${escape(st.name.toLowerCase())}</span></div>
        <div class="pet-upgrade" ${this.open ? "" : "hidden"}>${this.upgrade(pet, s.wallet.points)}</div>
        ${statBars(pet.stats, STAT_SCALE)}
        ${this.branches(pet)}
        <p id="pet-status" class="status" hidden></p>
      </div>
      ${others.length ? `<h2>Adopter un autre familier</h2>
        <p class="muted small">Gratuit, une fois chacun ; il évolue de son côté avec les points que tu lui donnes.</p>
        ${this.starterCards(others)}` : ""}`;
    this.bindStarters();

    this.box.querySelector(".pet-art")!.addEventListener("click", () => {
      this.open = !this.open;
      this.render();
    });
    this.box.querySelector(".rename")!.addEventListener("click", () => this.rename(pet));
    this.box.querySelectorAll<HTMLButtonElement>("[data-levels]").forEach((b) => b.addEventListener("click", () => this.buyLevels(pet, b.dataset.levels!)));
    this.box.querySelector<HTMLButtonElement>(".evolve")?.addEventListener("click", () => this.evolve(pet));
    this.box.querySelectorAll<HTMLButtonElement>(".pet-switch button").forEach((b) =>
      b.addEventListener("click", () => Number(b.dataset.id) !== pet.id && this.activate(Number(b.dataset.id))),
    );
  }

  /** What points buy now: levels, or the evolution at the stage's max level. */
  private upgrade(pet: PetView, points: number): string {
    const wallet = `<p class="muted small">Solde : <strong>✦ ${nf(points)}</strong> points</p>`;
    const n = pet.next_level;
    if (n) {
      const disabled = (cost: number) => (cost > points || this.busy ? "disabled" : "");
      return `${wallet}<div class="upgrade-buttons">
        <button type="button" class="primary" data-levels="1" ${disabled(n.cost)}>+1 niveau<span>✦ ${nf(n.cost)}</span></button>
        ${n.levels_5 > 1 ? `<button type="button" class="action" data-levels="${n.levels_5}" ${disabled(n.cost_5)}>+${n.levels_5} niveaux<span>✦ ${nf(n.cost_5)}</span></button>` : ""}
        ${n.affordable > 1 ? `<button type="button" class="action" data-levels="max" ${this.busy ? "disabled" : ""}>Max : +${n.affordable} niveaux${n.affordable_cost !== undefined ? `<span>✦ ${nf(n.affordable_cost)}</span>` : ""}</button>` : ""}
      </div>${n.cost > points ? `<p class="muted small">Il te manque ${nf(n.cost - points)} points : cours, explore, évalue tes sorties !</p>` : ""}`;
    }
    const e = pet.evolution;
    if (e) {
      const into = e.form ?? "sa forme finale";
      return `${wallet}<p class="small">Niveau ${pet.level} atteint : <strong>${escape(pet.name)}</strong> peut évoluer en <strong>${escape(into)}</strong> (${escape(e.stage.toLowerCase())}).</p>
        <div class="evolve-preview">${STAT_NAMES.map(([k, label]) => `<span>${label} ${pet.stats[k]} → <strong>${e.stats[k]}</strong></span>`).join("")}</div>
        <button type="button" class="primary evolve" ${e.cost > points || this.busy ? "disabled" : ""}>Faire évoluer<span>✦ ${nf(e.cost)}</span></button>
        ${e.cost > points ? `<p class="muted small">Il te manque ${nf(e.cost - points)} points.</p>` : ""}`;
    }
    return `<p class="small">${escape(pet.name)} a atteint son plein potentiel : niveau maximum de sa forme finale.</p>`;
  }

  /** From the adult stage: the final forms, and which one the running profile leans towards. */
  private branches(pet: PetView): string {
    const b = pet.evolution?.branches;
    if (!b) return "";
    const best = Math.max(...b.map((x) => x.score), 0.0001);
    return `<div class="pet-branches"><h3>Forme finale</h3>
      <p class="muted small">Elle dépend de ta façon de courir depuis l'arrivée de ${escape(pet.name)}.</p>
      ${b.map((x) => `<div class="branch ${x.leading ? "leading" : ""}">${petArt({ species: pet.species, stage: 4, branch: x.id, color: pet.color, type: x.type }, 52)}<div class="branch-text"><span>${escape(x.name)} <span class="type-badge t-${x.type}">${escape(x.type_name)}</span>
        <span class="muted small">${escape(x.hint)}</span></span><div class="track"><div style="width:${Math.round((100 * x.score) / best)}%"></div></div></div></div>`).join("")}</div>`;
  }

  // --- actions ---

  private async buyLevels(pet: PetView, count: string) {
    await this.post(`/api/game/pets/${pet.id}/levels`, { count: count === "max" ? "max" : Number(count), request_id: requestId() }, "level-up");
  }

  private async evolve(pet: PetView) {
    const into = pet.evolution?.form ?? "sa forme finale";
    if (!confirm(`Faire évoluer ${pet.name} en ${into} pour ${nf(pet.evolution!.cost)} points ?`)) return;
    await this.post(`/api/game/pets/${pet.id}/evolve`, { request_id: requestId() }, "evolved");
  }

  private async post(url: string, body: object, effect: string) {
    if (this.busy) return;
    this.busy = true;
    this.box.querySelectorAll<HTMLButtonElement>(".pet-upgrade button").forEach((b) => (b.disabled = true)); // no double tap
    let ok = false;
    let error: string | null = null;
    try {
      const r = await apiFetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) error = out.detail ?? `erreur ${r.status}`;
      ok = r.ok;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      this.busy = false; // before redrawing: the new buttons must be usable
    }
    await this.refresh(); // also after a refusal: the buttons come back as they should be
    if (error) this.status(error, true);
    if (ok) {
      this.box.querySelector(".pet-art")?.classList.add(effect);
      window.dispatchEvent(new CustomEvent("credits:changed")); // the balance in the header
    }
  }

  private async rename(pet: PetView) {
    const name = prompt("Nouveau nom ?", pet.name)?.trim();
    if (!name || name === pet.name) return;
    const r = await apiFetch(`/api/game/pets/${pet.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) });
    if (!r.ok) return this.status((await r.json().catch(() => ({}))).detail ?? "nom refusé", true);
    await this.refresh();
  }

  private async activate(id: number) {
    await apiFetch(`/api/game/pets/${id}/activate`, { method: "POST" });
    await this.refresh();
  }

  private status(text: string, error = false) {
    const el = document.getElementById("pet-status");
    if (!el) return;
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("error", error);
  }
}

const art = (p: PetView) => ({ species: p.species, stage: p.stage.index, branch: p.branch, color: p.color, type: p.type });

function statBars(stats: Stats, scale: number): string {
  return `<div class="stat-bars">${STAT_NAMES.map(
    ([k, label]) => `<div class="stat"><span>${label}</span><div class="track"><div style="width:${Math.min(100, (100 * stats[k]) / scale)}%"></div></div><strong>${stats[k]}</strong></div>`,
  ).join("")}</div>`;
}
