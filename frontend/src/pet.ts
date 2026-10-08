/**
 * « Familier » tab: the three starters to adopt (all of them, each once; they grow each on their own side),
 * a row to switch between my familiers, then the active one. A tap on its picture
 * opens what points buy: levels (+1, +5, as many as possible), and at the stage's max level the evolution
 * (from the adult stage: which final form the running profile leans towards). « Boutique »: rarer familiers,
 * bigger and stronger, with more abilities, paid in points or gems (each purchase says exactly what it gives).
 * Everything is decided by the server; this only shows it.
 */
import { apiFetch } from "./api";
import { BattleView } from "./battle";
import { escape } from "./format";
import { FriendsView } from "./friends";
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

interface Ability {
  id: string;
  name: string;
  kind: "strike" | "guard" | "heal" | "haste" | "drain";
  power: number;
  value: number;
  description: string;
  stage: string;
  branch: string | null;
  unlocked: boolean;
}

interface PetView {
  id: number;
  name: string;
  species: string;
  form: string;
  type: string;
  type_name: string;
  type2: string | null;
  type2_name: string | null;
  color: string;
  active: boolean;
  origin: string;
  stage: { index: number; id: string; name: string; max_level: number; final: boolean };
  level: number;
  branch: string | null;
  stats: Stats;
  rarity: string | null;
  rarity_name: string | null;
  abilities: Ability[];
  kit: { id: string; name: string; kind: "attack" | "defense"; type: string; power: number; hits: number; target: string; description: string }[];
  next_level: { cost: number; cost_5: number; levels_5: number; affordable: number; affordable_cost?: number } | null;
  evolution: { stage: string; level: number; ready: boolean; cost: number; stats: Stats; form: string | null; branches?: BranchView[] } | null;
}

interface Starter {
  id: string;
  type: string;
  type_name: string;
  type2?: string | null;
  type2_name?: string | null;
  names: string[];
  color: string;
  description: string;
  base: Stats;
  branches: { id: string; name: string; type: string; hint: string }[];
  adopted: boolean;
  rarity: string | null;
  rarity_name: string | null;
  total: number;
  abilities: Ability[];
  final_stats: Stats;
}

interface ShopState {
  items: { id: string; price_points: number | null; price_gems: number | null; owned: boolean; species: Starter }[];
  wallet: { points: number; gems: number };
  payments: string;
  gem_packs: { id: string; gems: number; price_eur: number; label: string }[];
  starter_total: number;
}

interface GameState {
  wallet: { points: number; gems: number };
  starter_chosen: boolean;
  pets: PetView[];
}

const STAT_NAMES: [keyof Stats, string][] = [["hp", "PV"], ["attack", "Attaque"], ["defense", "Défense"], ["speed", "Vitesse"]];
const STAT_SCALE = 400; // the bars' full width (about the best final form at level 100)
const nf = (n: number) => n.toLocaleString("fr-FR");
const KIND_ICON: Record<Ability["kind"], string> = { strike: "⚔", guard: "⛨", heal: "✚", haste: "➤", drain: "♥" };

function abilityLine(a: Ability, branchName?: string): string {
  const effect =
    a.kind === "strike" ? `puissance ${a.power}` :
    a.kind === "drain" ? `puissance ${a.power}, soigne ${a.value} % des dégâts` :
    a.kind === "heal" ? `soigne ${a.value} % des PV` :
    a.kind === "guard" ? `défense +${a.value} %` : `vitesse +${a.value} %`;
  return `<li class="ability k-${a.kind} ${a.unlocked ? "on" : ""}"><span class="ability-icon">${KIND_ICON[a.kind]}</span>
    <div><strong>${escape(a.name)}</strong> <span class="muted small">${effect}</span>
    <span class="muted small">${a.unlocked ? escape(a.description) : `Débloquée au stade ${escape(a.stage.toLowerCase())}${branchName ? ` (forme ${escape(branchName)})` : ""}`}</span></div></li>`;
}

function rarityBadge(rarity: string | null, name: string | null): string {
  return rarity ? `<span class="rarity r-${rarity}">${escape(name ?? rarity)}</span>` : "";
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export class PetTab {
  private state: GameState | null = null;
  private open = false; // the upgrade sheet under the picture
  private busy = false;
  private box = document.getElementById("pet-body")!;
  private view: "pets" | "shop" | "battles" | "friends" = "pets";
  readonly battle = new BattleView(() => this.refresh()); // back to the trail when a battle closes
  private friends = new FriendsView(this.battle);
  private shop: ShopState | null = null;

  async refresh() {
    const r = await apiFetch("/api/game");
    if (!r.ok) {
      this.box.innerHTML = `<p class="status error">Familier indisponible (${r.status}).</p>`;
      return;
    }
    this.state = (await r.json()) as GameState;
    if (this.view === "battles") return this.battle.renderTrail(this.box, this.views(), () => this.bindViews());
    if (this.view === "friends") return this.friends.render(this.box, this.views(), () => this.bindViews());
    if (this.view === "shop") {
      const rs = await apiFetch("/api/game/shop");
      if (rs.ok) {
        this.shop = (await rs.json()) as ShopState;
        return this.renderShop();
      }
      this.view = "pets";
    }
    const rs = await apiFetch("/api/game/starters");
    this.starters = rs.ok ? ((await rs.json()) as { starters: Starter[] }).starters : [];
    if (!this.state.pets.length) this.renderStarters();
    else this.render();
  }

  /** « Mes familiers » / « Boutique », above both views. */
  private views(): string {
    return `<div class="pet-views" role="tablist">
      <button type="button" role="tab" data-view="pets" aria-selected="${this.view === "pets"}">Mes familiers</button>
      <button type="button" role="tab" data-view="battles" aria-selected="${this.view === "battles"}">Combats ⚔</button>
      <button type="button" role="tab" data-view="friends" aria-selected="${this.view === "friends"}">Amis</button>
      <button type="button" role="tab" data-view="shop" aria-selected="${this.view === "shop"}">Boutique <span class="shop-spark">✦</span></button></div>`;
  }

  private bindViews() {
    this.box.querySelectorAll<HTMLButtonElement>(".pet-views button").forEach((b) =>
      b.addEventListener("click", () => {
        const v = b.dataset.view as "pets" | "shop" | "battles" | "friends";
        if (v === this.view) return;
        this.view = v;
        this.refresh();
      }),
    );
  }

  private starters: Starter[] = [];

  // --- the starter ---

  private renderStarters() {
    this.box.innerHTML = `${this.views()}
      <h2>Adopte ton premier familier</h2>
      <p class="muted small">Il grandit avec les points que tu gagnes en courant et en explorant. Tu pourras adopter les deux autres
        quand tu voudras : chacun évolue de son côté.</p>
      ${this.starterCards(this.starters)}
      <p id="pet-status" class="status" hidden></p>`;
    this.bindStarters();
    this.bindViews();
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
    this.box.innerHTML = `${this.views()}
      ${s.pets.length > 1 ? `<div class="pet-switch" role="tablist">${s.pets
        .map((p) => `<button type="button" role="tab" data-id="${p.id}" aria-selected="${p.id === pet.id}">${petArt(art(p), 46)}
          <span>${escape(p.name)}</span><span class="muted">niv. ${p.level}</span></button>`)
        .join("")}</div>` : ""}
      <div class="pet-card t-${pet.type}">
        <div class="pet-head">
          <div><h2 class="pet-name">${escape(pet.name)} <button type="button" class="text-btn rename" title="Renommer">✎</button></h2>
            <span class="muted small">${escape(pet.form)} · ${escape(st.name)}</span></div>
          <span class="badges">${rarityBadge(pet.rarity, pet.rarity_name)}<span class="type-badge t-${pet.type}">${escape(pet.type_name)}</span>${pet.type2 ? `<span class="type-badge t-${pet.type2}">${escape(pet.type2_name ?? "")}</span>` : ""}</span>
        </div>
        <button type="button" class="pet-art ${pet.rarity ? `r-${pet.rarity}` : ""} ${this.open ? "" : "hint"}" aria-expanded="${this.open}" aria-label="Faire progresser ${escape(pet.name)}">
          ${petArt(art(pet), 180)}
        </button>
        <div class="pet-level"><strong>Niv. ${pet.level}</strong><div class="track"><div style="width:${levelPct}%"></div></div>
          <span class="muted small">max ${st.max_level} au stade ${escape(st.name.toLowerCase())}</span></div>
        <div class="pet-upgrade" ${this.open ? "" : "hidden"}>${this.upgrade(pet, s.wallet.points)}</div>
        ${statBars(pet.stats, STAT_SCALE)}
        <div class="abilities"><h3>En combat (${escape(pet.type_name)}${pet.type2 ? ` et ${escape(pet.type2_name ?? "")}` : ""})</h3><ul>${pet.kit
          .map((m) => `<li class="ability on k-${m.kind === "defense" ? "guard" : "strike"}"><span class="ability-icon">${m.kind === "defense" ? "⛨" : "⚔"}</span>
            <div><strong>${escape(m.name)}</strong> <span class="muted small">${m.kind === "defense" ? "défense" : `puissance ${m.power}${m.hits > 1 ? ` ×${m.hits}` : ""}${m.target === "all" ? ", tous les adversaires" : ""}`}</span>
            <span class="muted small">${escape(m.description)}</span></div></li>`)
          .join("")}</ul></div>
        ${pet.abilities.length ? `<div class="abilities"><h3>Capacités spéciales</h3><ul>${pet.abilities
          .filter((a) => !a.branch || !pet.branch || a.branch === pet.branch)
          .map((a) => abilityLine(a, a.branch ? pet.evolution?.branches?.find((b) => b.id === a.branch)?.name : undefined))
          .join("")}</ul></div>` : ""}
        ${this.branches(pet)}
        <p id="pet-status" class="status" hidden></p>
      </div>
      ${others.length ? `<h2>Adopter un autre familier</h2>
        <p class="muted small">Gratuit, une fois chacun ; il évolue de son côté avec les points que tu lui donnes.</p>
        ${this.starterCards(others)}` : ""}`;
    this.bindStarters();
    this.bindViews();

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

  // --- the shop ---

  private renderShop() {
    const sh = this.shop!;
    const pay = sh.payments !== "disabled";
    this.box.innerHTML = `${this.views()}
      <div class="shop-wallet"><span><strong>✦ ${nf(sh.wallet.points)}</strong> points</span><span><strong class="gem">◆ ${nf(sh.wallet.gems)}</strong> gemmes</span></div>
      <p class="muted small">Des familiers rares, plus grands, plus forts, avec plus de capacités. Chaque achat est exactement ce qui
        est affiché : pas de tirage au sort. Tout s'obtient aussi avec les points gagnés en courant.</p>
      <div class="shop-items">${sh.items.map((it) => this.shopCard(it, sh)).join("")}</div>
      <h2>Gemmes</h2>
      <div class="gem-packs">${sh.gem_packs
        .map((g) => `<button type="button" class="gem-pack" data-pack="${g.id}" ${pay ? "" : "disabled"}><strong class="gem">◆ ${nf(g.gems)}</strong>
          ${g.label ? `<span class="bonus">${escape(g.label)}</span>` : ""}<span>${g.price_eur.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })}</span></button>`)
        .join("")}</div>
      <p class="muted small">${pay ? (sh.payments === "mock" ? "Mode test : aucun paiement réel n'est demandé." : "") : "L'achat de gemmes n'est pas encore disponible : les familiers s'achètent avec tes points en attendant."}</p>
      <p id="pet-status" class="status" hidden></p>`;
    this.bindViews();
    this.box.querySelectorAll<HTMLButtonElement>("[data-buy]").forEach((b) =>
      b.addEventListener("click", () => this.buyItem(sh.items.find((i) => i.id === b.dataset.buy)!, b.dataset.currency as "points" | "gems")),
    );
    this.box.querySelectorAll<HTMLButtonElement>("[data-pack]").forEach((b) => b.addEventListener("click", () => this.buyGems(b.dataset.pack!)));
  }

  private shopCard(it: ShopState["items"][number], sh: ShopState): string {
    const sp = it.species;
    const final = sp.branches[0];
    const plus = sh.starter_total ? Math.round((100 * (sp.total - sh.starter_total)) / sh.starter_total) : 0;
    const price = (cur: "points" | "gems", v: number | null) =>
      v === null ? "" : `<button type="button" class="${cur === "points" ? "primary" : "action gem-btn"}" data-buy="${it.id}" data-currency="${cur}"
        ${it.owned || v > sh.wallet[cur] ? "disabled" : ""}>${cur === "points" ? "✦" : "◆"} ${nf(v)}</button>`;
    return `<article class="shop-card r-${sp.rarity}">
      <div class="shop-top">${rarityBadge(sp.rarity, sp.rarity_name)}<span class="badges"><span class="type-badge t-${sp.type}">${escape(sp.type_name)}</span>${sp.type2 ? `<span class="type-badge t-${sp.type2}">${escape(sp.type2_name ?? "")}</span>` : ""}</span></div>
      <div class="shop-art">${petArt({ species: sp.id, stage: 4, branch: final.id, color: sp.color, type: final.type }, 170)}
        <div class="shop-line">${[0, 1, 2, 3].map((st) => petArt({ species: sp.id, stage: st, color: sp.color, type: sp.type }, 40)).join("")}</div></div>
      <h3>${escape(final.name)}</h3>
      <p class="muted small">${sp.names.map(escape).join(" → ")} → ${escape(final.name)}</p>
      <p class="small">${escape(sp.description)}</p>
      <p class="shop-power"><strong>${sp.total}</strong> de stats de base${plus > 0 ? ` <span class="plus">+${plus} % vs les starters</span>` : ""}</p>
      ${statBars(sp.final_stats, STAT_SCALE * 1.3)}
      <ul class="abilities">${sp.abilities.map((a) => abilityLine({ ...a, unlocked: true })).join("")}</ul>
      <div class="shop-buy">${it.owned ? `<span class="owned">Dans ta collection</span>` : `${price("points", it.price_points)}${price("gems", it.price_gems)}`}</div>
    </article>`;
  }

  private async buyItem(it: ShopState["items"][number], currency: "points" | "gems") {
    const sp = it.species;
    const price = currency === "points" ? `${nf(it.price_points!)} points` : `${nf(it.price_gems!)} gemmes`;
    if (!confirm(`Tu obtiens : un œuf de ${sp.names[1]} (${sp.rarity_name}), qui deviendra ${sp.branches[0].name}.\nPrix : ${price}.\n\nConfirmer l'achat ?`)) return;
    const r = await apiFetch("/api/game/shop/buy", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ item: it.id, currency, request_id: requestId() }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) return this.status(out.detail ?? `erreur ${r.status}`, true);
    window.dispatchEvent(new CustomEvent("credits:changed"));
    this.view = "pets"; // straight to the new familier, the active one now
    this.open = true;
    await this.refresh();
    this.box.querySelector(".pet-art")?.classList.add("evolved");
  }

  private async buyGems(pack: string) {
    const r = await apiFetch("/api/game/gems/buy", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ pack, request_id: requestId() }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) return this.status(out.detail ?? `erreur ${r.status}`, true);
    await this.refresh();
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
