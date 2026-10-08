/**
 * Battles against bots: the trail of levels (mobs alone or in groups, a mid-boss every 5 levels, a big boss
 * every 10), then a full-screen arena where each turn I pick a move (and a target against a group). The
 * server resolves the turn; this plays its events back: the move's own animation (one per attack and
 * defence, in the style of its type), damage numbers, dodges, heals, K.O., a boss's rage and reinforcements.
 * Friendly battles, live (`openPvp`): the same arena; both players choose, the round is played back once both
 * have (or when the time is up), the screen polls for my friend's move.
 */
import { apiFetch } from "./api";
import { escape } from "./format";
import { petArt } from "./pet-art";

interface Move {
  id: string;
  name: string;
  type: string;
  kind: "attack" | "defense" | "special";
  target: "one" | "all";
  anim: string;
  description: string;
  power: number;
  hits: number;
  cooldown: number;
  priority: boolean;
}

interface Fighter {
  id: string;
  side: "player" | "enemy";
  name: string;
  species: string;
  stage: number;
  branch: string | null;
  type: string;
  type_name: string;
  color: string;
  hp: number;
  max_hp: number;
  boss: "mid" | "big" | null;
  angry: boolean;
  level: number | null;
  effects: string[];
  power: number;
  moves?: Move[];
}

interface BattleState {
  id: number;
  pvp?: boolean;
  friend?: string;
  mode?: string;
  round?: number;
  rounds?: { turn: number; events: Ev[] }[];
  played?: boolean;
  friend_played?: boolean;
  seconds_left?: number;
  result?: "won" | "lost" | "draw";
  level: number;
  kind: "mobs" | "mid_boss" | "boss";
  turn: number;
  max_turns: number;
  status: "running" | "won" | "lost" | "done" | "invited" | "declined" | "cancelled" | "expired";
  end_reason: string;
  fighters: Fighter[];
  events?: Ev[];
  reward?: number;
}

type Ev = { t: string; [k: string]: any };

interface Level {
  level: number;
  kind: "mobs" | "mid_boss" | "boss";
  open: boolean;
  won: boolean;
  reward: number;
  enemies: Fighter[];
}

interface Trail {
  cleared: number;
  running: number | null;
  daily: { rewarded: number; limit: number };
  levels: Level[];
}

const TYPE_ICON: Record<string, string> = { montagne: "▲", vitesse: "ϟ", endurance: "◉", nocturne: "☾", exploration: "❦" };
const KIND_LABEL = { mobs: "", mid_boss: "Boss", boss: "Grand boss" };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const nf = (n: number) => n.toLocaleString("fr-FR");

const art = (f: Fighter, size: number) => petArt({ species: f.species, stage: f.stage, branch: f.branch, color: f.color, type: f.type }, size);

export class BattleView {
  private overlay: HTMLElement;
  private state: BattleState | null = null;
  private target: string | null = null;
  private playing = false;
  private poll = 0;

  constructor(private onClose: () => void) {
    this.overlay = document.createElement("div");
    this.overlay.className = "battle";
    this.overlay.hidden = true;
    document.body.appendChild(this.overlay);
  }

  // --- the trail ---

  async renderTrail(box: HTMLElement, header: string, bind: () => void) {
    const r = await apiFetch("/api/game/battles");
    if (!r.ok) {
      box.innerHTML = `${header}<p class="status error">Combats indisponibles (${r.status}).</p>`;
      return bind();
    }
    const t = (await r.json()) as Trail;
    const left = Math.max(0, t.daily.limit - t.daily.rewarded);
    box.innerHTML = `${header}
      <div class="trail-head"><span><strong>Niveau ${t.cleared + 1}</strong> à conquérir</span>
        <span class="muted small">${left ? `${left} victoire${left > 1 ? "s" : ""} récompensée${left > 1 ? "s" : ""} encore aujourd'hui` : "Plus de points aujourd'hui (la progression continue)"}</span></div>
      ${t.running ? `<button type="button" class="primary resume">Reprendre le combat en cours</button>` : ""}
      <p class="muted small">Ton familier actif combat seul, face à des mobs seuls ou en groupe. Un boss tous les 5 niveaux, un grand boss
        tous les 10. Chaque type a ses 2 attaques et sa défense ; les types comptent (▲ Montagne bat ϟ Vitesse, qui bat ◉ Endurance,
        qui bat ▲ Montagne…).</p>
      <ol class="trail">${t.levels.map((l, i) => this.levelNode(l, i)).join("")}</ol>`;
    bind();
    box.querySelector(".resume")?.addEventListener("click", () => this.resume(t.running!));
    box.querySelectorAll<HTMLButtonElement>("[data-level]").forEach((b) => b.addEventListener("click", () => this.start(Number(b.dataset.level))));
  }

  private levelNode(l: Level, i: number): string {
    const state = l.won ? "won" : l.open ? "open" : "locked";
    const shown = l.enemies.slice(0, 3);
    return `<li class="lvl ${state} k-${l.kind} ${i % 2 ? "right" : "left"}">
      <div class="lvl-num">${l.won ? "✓" : l.kind === "boss" ? "♛" : l.kind === "mid_boss" ? "♜" : l.level}</div>
      <div class="lvl-body">
        <div class="lvl-title"><strong>Niveau ${l.level}</strong>${KIND_LABEL[l.kind] ? ` <span class="boss-tag ${l.kind}">${KIND_LABEL[l.kind]}</span>` : ""}</div>
        <div class="lvl-enemies">${shown.map((e) => `<span class="lvl-enemy" title="${escape(e.name)}">${art(e, l.kind === "mobs" ? 38 : 52)}</span>`).join("")}</div>
        <span class="muted small">${l.enemies.map((e) => `${TYPE_ICON[e.type]} ${escape(e.name)}`).join(" · ")}</span>
        <span class="small">✦ ${nf(l.reward)} points${l.won ? " (déjà gagné : 25 %)" : ""}</span>
        ${l.open ? `<button type="button" class="${l.won ? "action" : "primary"}" data-level="${l.level}">${l.won ? "Rejouer" : "Combattre"}</button>` : ""}
      </div></li>`;
  }

  // --- the arena ---

  private async start(level: number) {
    const r = await apiFetch("/api/game/battles", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ level }) });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) return alert(out.detail ?? `erreur ${r.status}`);
    this.open(out as BattleState);
  }

  private async resume(id: number) {
    const r = await apiFetch(`/api/game/battles/${id}`);
    if (r.ok) this.open((await r.json()) as BattleState);
  }

  /** A friendly battle, live: the arena, kept up to date by polling (my friend's move, the time left). */
  async openPvp(id: number) {
    if (this.state?.pvp && this.state.id === id) return;
    const r = await apiFetch(`/api/game/pvp/${id}`);
    if (!r.ok) return;
    const s = (await r.json()) as BattleState;
    s.round = s.rounds?.length ? s.rounds[s.rounds.length - 1].turn : s.round ?? 0;
    this.open(s);
    this.pvpTick();
  }

  get isOpen(): boolean {
    return this.state !== null;
  }

  private async pvpTick() {
    clearTimeout(this.poll);
    const s = this.state;
    if (!s?.pvp || this.overlay.hidden) return;
    if (!this.playing) {
      const r = await apiFetch(`/api/game/pvp/${s.id}?since=${s.round ?? 0}`).catch(() => null);
      if (r?.ok) await this.pvpUpdate((await r.json()) as BattleState);
    }
    if (this.state?.pvp && this.state.status === "running") this.poll = window.setTimeout(() => this.pvpTick(), 1200);
  }

  /** New rounds to play back, then the state as the server has it. */
  private async pvpUpdate(next: BattleState) {
    const s = this.state!;
    const rounds = next.rounds ?? [];
    if (rounds.length) {
      this.playing = true;
      for (const r of rounds) await this.animate(r.events);
      this.playing = false;
    }
    next.round = rounds.length ? rounds[rounds.length - 1].turn : s.round;
    this.state = next;
    this.drawFighters();
    this.drawMoves();
    this.pvpStatus();
    if (next.status === "done") this.showResult();
  }

  private pvpStatus() {
    const s = this.state!;
    if (!s.pvp || s.status !== "running") return;
    const left = s.seconds_left ?? 0;
    this.log(s.played ? `En attente de ${s.friend}… (${left} s)` : `${s.friend_played ? `${s.friend} a choisi. ` : ""}À toi : choisis ton attaque (${left} s)`);
  }

  private open(s: BattleState) {
    clearTimeout(this.poll);
    this.state = s;
    this.target = null;
    this.overlay.hidden = false;
    document.body.classList.add("in-battle");
    this.overlay.innerHTML = `
      <div class="arena t-${s.fighters.find((f) => f.side === "player")!.type}">
        <header class="arena-head">${s.pvp ? `<strong>Contre ${escape(s.friend ?? "")}</strong> <span class="boss-tag mid_boss">Amical${s.mode === "balanced" ? " · équilibré" : ""}</span>`
          : `<strong>Niveau ${s.level}</strong>${KIND_LABEL[s.kind] ? ` <span class="boss-tag ${s.kind}">${KIND_LABEL[s.kind]}</span>` : ""}`}
          <span class="turn muted small"></span><button type="button" class="text-btn flee">${s.pvp ? "Abandonner" : "Fuir"}</button></header>
        <div class="foes"></div>
        <div class="banner" hidden></div>
        <div class="me"></div>
        <div class="log" aria-live="polite"></div>
        <div class="moves"></div>
        <div class="result" hidden></div>
      </div>`;
    this.overlay.querySelector(".flee")!.addEventListener("click", () => this.flee());
    this.drawFighters();
    this.drawMoves();
  }

  private close() {
    clearTimeout(this.poll);
    this.overlay.hidden = true;
    this.overlay.innerHTML = "";
    document.body.classList.remove("in-battle");
    this.state = null;
    this.onClose();
  }

  private async flee() {
    if (this.playing) return;
    const s = this.state;
    if (s?.status === "running" && !confirm(s.pvp ? `Abandonner ? ${s.friend} gagne le combat.` : "Fuir ce combat ? Il sera perdu.")) return;
    if (s?.status === "running") await apiFetch(s.pvp ? `/api/game/pvp/${s.id}/forfeit` : `/api/game/battles/${s.id}/flee`, { method: "POST" });
    this.close();
  }

  private sprite(f: Fighter): string {
    const size = f.side === "player" ? 130 : f.boss === "big" ? 160 : f.boss === "mid" ? 140 : 100;
    const pct = Math.round((100 * f.hp) / f.max_hp);
    return `<div class="fighter ${f.side} ${f.boss ? `boss-${f.boss}` : ""} ${f.hp <= 0 ? "down" : ""} ${f.angry ? "angry" : ""}" data-id="${f.id}">
      <div class="plate"><span class="fname">${escape(f.name)}</span><span class="ftype t-${f.type}">${TYPE_ICON[f.type]} ${escape(f.type_name)}</span>
        <div class="hp"><div class="hp-fill ${pct < 25 ? "low" : pct < 50 ? "mid" : ""}" style="width:${pct}%"></div></div>
        <span class="hp-num">${nf(f.hp)} / ${nf(f.max_hp)}</span><span class="fx-icons">${f.effects.map((e) => `<i class="st-${e}"></i>`).join("")}</span></div>
      <div class="body">${art(f, size)}<div class="fx-layer"></div></div></div>`;
  }

  private drawFighters() {
    const s = this.state!;
    const foes = s.fighters.filter((f) => f.side === "enemy");
    const alive = foes.filter((f) => f.hp > 0);
    if (!this.target || !alive.some((f) => f.id === this.target)) this.target = alive[0]?.id ?? null;
    const box = this.overlay.querySelector(".foes")!;
    box.className = `foes n${foes.length}`;
    box.innerHTML = foes.map((f) => this.sprite(f)).join("");
    this.overlay.querySelector(".me")!.innerHTML = this.sprite(s.fighters.find((f) => f.side === "player")!);
    this.overlay.querySelector(".turn")!.textContent = s.turn ? `Tour ${s.turn} / ${s.max_turns}` : "";
    box.querySelectorAll<HTMLElement>(".fighter.enemy").forEach((el) => {
      el.classList.toggle("targeted", alive.length > 1 && el.dataset.id === this.target);
      el.addEventListener("click", () => {
        if (el.classList.contains("down")) return;
        this.target = el.dataset.id!;
        this.drawFighters();
      });
    });
  }

  private drawMoves() {
    const s = this.state!;
    const me = s.fighters.find((f) => f.side === "player")!;
    const box = this.overlay.querySelector(".moves")!;
    if (s.status !== "running" || (s.pvp && s.played)) {
      box.innerHTML = s.pvp && s.played && s.status === "running" ? `<p class="waiting">En attente de ${escape(s.friend ?? "")}…</p>` : "";
      return;
    }
    const several = s.fighters.filter((f) => f.side === "enemy" && f.hp > 0).length > 1;
    box.innerHTML = (me.moves ?? [])
      .map((m) => {
        const info = m.kind === "defense" ? "défense" : m.kind === "special" ? "spéciale" : `${m.power}${m.hits > 1 ? ` ×${m.hits}` : ""}${m.target === "all" ? " · zone" : ""}${m.priority ? " · en premier" : ""}`;
        return `<button type="button" class="move k-${m.kind} t-${m.type}" data-move="${m.id}" ${m.cooldown > 0 || this.playing ? "disabled" : ""} title="${escape(m.description)}">
          <span class="mv-icon">${TYPE_ICON[m.type]}</span><span class="mv-name">${escape(m.name)}</span><span class="mv-info">${m.cooldown > 0 ? `prête dans ${m.cooldown} tour${m.cooldown > 1 ? "s" : ""}` : info}</span></button>`;
      })
      .join("") + (several ? `<p class="muted small hint-target">Touche un adversaire pour le viser.</p>` : "");
    box.querySelectorAll<HTMLButtonElement>("[data-move]").forEach((b) => b.addEventListener("click", () => this.play(b.dataset.move!)));
  }

  private async play(move: string) {
    if (this.playing || !this.state) return;
    if (this.state.pvp) return this.playPvp(move);
    this.playing = true;
    this.overlay.querySelectorAll<HTMLButtonElement>(".move").forEach((b) => (b.disabled = true));
    try {
      const r = await apiFetch(`/api/game/battles/${this.state.id}/turn`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ move, target: this.target }),
      });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) {
        this.log(out.detail ?? `erreur ${r.status}`);
        return;
      }
      await this.animate((out as BattleState).events ?? []);
      this.state = out as BattleState;
      this.drawFighters();
      if (this.state.status !== "running") this.showResult();
    } finally {
      this.playing = false;
      this.drawMoves();
    }
  }

  private async playPvp(move: string) {
    const s = this.state!;
    this.overlay.querySelectorAll<HTMLButtonElement>(".move").forEach((b) => (b.disabled = true));
    const r = await apiFetch(`/api/game/pvp/${s.id}/move`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ move, target: this.target }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) {
      this.log(out.detail ?? `erreur ${r.status}`);
      return this.drawMoves();
    }
    out.rounds = (out.rounds ?? []).filter((x: { turn: number }) => x.turn > (s.round ?? 0));
    await this.pvpUpdate(out as BattleState);
    this.pvpTick();
  }

  // --- playing a turn back ---

  private el(id: string): HTMLElement | null {
    return this.overlay.querySelector(`.fighter[data-id="${id}"]`);
  }

  private fighter(id: string): Fighter | undefined {
    return this.state!.fighters.find((f) => f.id === id);
  }

  private async animate(events: Ev[]) {
    for (const e of events) {
      switch (e.t) {
        case "move": {
          const actor = this.fighter(e.actor);
          this.banner(`${actor?.name ?? ""} : ${e.name}`, e.type);
          this.log(`${actor?.name ?? ""} utilise ${e.name}.`);
          const el = this.el(e.actor);
          if (e.kind !== "defense") el?.classList.add(actor?.side === "player" ? "lunge-up" : "lunge-down");
          const on = e.kind === "defense" || (e.kind === "special" && !e.targets.some((t: string) => t !== e.actor)) ? [e.actor] : e.targets;
          on.forEach((t: string) => this.fx(t, e.anim, e.type));
          await sleep(e.kind === "defense" ? 650 : 520);
          el?.classList.remove("lunge-up", "lunge-down");
          break;
        }
        case "hit":
          this.setHp(e.target, e.hp);
          this.float(e.target, `${e.dot ? "" : "−"}${e.dmg}`, e.crit ? "crit" : e.dot ? "dot" : "dmg");
          if (e.crit) this.float(e.target, "Critique !", "tag", 140);
          if (e.eff === "super") this.float(e.target, "Super efficace !", "super", 260);
          if (e.eff === "weak") this.float(e.target, "Peu efficace…", "weak", 260);
          this.el(e.target)?.classList.add("shake");
          await sleep(e.dot ? 300 : 260);
          this.el(e.target)?.classList.remove("shake");
          break;
        case "dodge":
          this.float(e.target, "Esquivé !", "tag");
          this.fx(e.target, "afterimage", this.fighter(e.target)?.type ?? "");
          await sleep(380);
          break;
        case "heal":
          this.setHp(e.target, e.hp);
          this.float(e.target, `+${e.amount}`, "heal");
          await sleep(300);
          break;
        case "status":
          this.float(e.target, { guard: "Défense ↑", dodge: "Esquive prête", regen: "Régénération", dot: "Rongé…", haste: "Vitesse ↑" }[e.status as string] ?? "", "tag");
          await sleep(260);
          break;
        case "ko":
          this.el(e.target)?.classList.add("down");
          this.log(`${e.name} est K.O. !`);
          await sleep(450);
          break;
        case "phase":
          this.overlay.querySelector(".arena")?.classList.add("rage");
          this.banner(e.text, "rage");
          this.log(e.text);
          await sleep(900);
          this.overlay.querySelector(".arena")?.classList.remove("rage");
          break;
        case "summon": {
          const f = e.fighter as Fighter;
          this.state!.fighters.push(f);
          const box = this.overlay.querySelector(".foes")!;
          box.insertAdjacentHTML("beforeend", this.sprite(f));
          box.className = `foes n${box.children.length}`;
          box.lastElementChild?.classList.add("arrive");
          this.log(`${f.name} arrive en renfort !`);
          await sleep(500);
          break;
        }
      }
    }
  }

  private setHp(id: string, hp: number) {
    const f = this.fighter(id);
    const el = this.el(id);
    if (!f || !el) return;
    f.hp = hp;
    const pct = Math.max(0, Math.round((100 * hp) / f.max_hp));
    const fill = el.querySelector<HTMLElement>(".hp-fill")!;
    fill.style.width = `${pct}%`;
    fill.className = `hp-fill ${pct < 25 ? "low" : pct < 50 ? "mid" : ""}`;
    el.querySelector(".hp-num")!.textContent = `${nf(hp)} / ${nf(f.max_hp)}`;
  }

  private float(id: string, text: string, kind: string, delay = 0) {
    const layer = this.el(id)?.querySelector(".fx-layer");
    if (!layer || !text) return;
    setTimeout(() => {
      const s = document.createElement("span");
      s.className = `float ${kind}`;
      s.textContent = text;
      s.style.left = `${40 + Math.random() * 20}%`;
      layer.appendChild(s);
      setTimeout(() => s.remove(), 1100);
    }, delay);
  }

  private banner(text: string, type: string) {
    const b = this.overlay.querySelector<HTMLElement>(".banner")!;
    b.hidden = false;
    b.className = `banner t-${type}`;
    b.textContent = text;
    void b.offsetWidth;
    b.classList.add("show");
  }

  private log(text: string) {
    const l = this.overlay.querySelector(".log");
    if (l) l.textContent = text;
  }

  /** The move's own animation on a fighter (fx-<anim>, see style.css): rocks, bolts, claws, leaves, roots… */
  private fx(id: string, anim: string, type: string) {
    const layer = this.el(id)?.querySelector(".fx-layer");
    if (!layer) return;
    const d = document.createElement("div");
    const base = anim.startsWith("special-") ? "special" : anim;
    d.className = `fx fx-${base} t-${type}`;
    d.innerHTML = FX_PARTS[base]?.() ?? "";
    layer.appendChild(d);
    setTimeout(() => d.remove(), 1200);
  }

  private showResult() {
    const s = this.state!;
    const box = this.overlay.querySelector<HTMLElement>(".result")!;
    if (s.pvp) {
      clearTimeout(this.poll);
      box.hidden = false;
      box.className = `result ${s.result === "won" ? "won" : "lost"}`;
      box.innerHTML = `<h2>${s.result === "won" ? "Victoire !" : s.result === "draw" ? "Égalité" : "Défaite"}</h2>
        <p>${s.end_reason === "abandon" ? (s.result === "won" ? `${escape(s.friend ?? "")} a abandonné.` : "Tu as abandonné.") : escape(s.end_reason)}</p>
        <p class="muted small">Combat amical : pas de points, le bilan est mis à jour.</p>
        <div class="result-buttons"><button type="button" class="primary back">Retour</button></div>`;
      box.querySelector(".back")!.addEventListener("click", () => this.close());
      return;
    }
    const won = s.status === "won";
    const ev = s.events?.find((e) => e.t === "reward");
    box.hidden = false;
    box.className = `result ${won ? "won" : "lost"}`;
    box.innerHTML = `<h2>${won ? "Victoire !" : "Défaite"}</h2>
      <p>${won ? (s.reward ? `<strong>+${nf(s.reward)} points</strong>${ev?.first ? " · niveau suivant débloqué" : ""}` : ev?.first ? "Niveau suivant débloqué (plus de points aujourd'hui)" : "Plus de points aujourd'hui pour ce combat")
        : s.end_reason === "à bout de souffle" ? "À bout de souffle : trop de tours. Change de tactique ou de familier." : "Ton familier est K.O. Monte-le de niveau, fais-le évoluer ou choisis-en un qui a l'avantage du type."}</p>
      <div class="result-buttons">${won && ev?.first ? `<button type="button" class="primary next">Niveau ${s.level + 1}</button>` : ""}
        <button type="button" class="${won && ev?.first ? "action" : "primary"} back">Retour au sentier</button></div>`;
    if (won) window.dispatchEvent(new CustomEvent("credits:changed"));
    box.querySelector(".back")!.addEventListener("click", () => this.close());
    box.querySelector(".next")?.addEventListener("click", () => this.start(s.level + 1));
  }
}

/** Inner pieces of each animation (styled and moved by CSS). */
const n = (k: number, html: (i: number) => string) => Array.from({ length: k }, (_, i) => html(i)).join("");
const FX_PARTS: Record<string, () => string> = {
  rockfall: () => n(5, (i) => `<i class="rock" style="--i:${i}"></i>`),
  smash: () => `<i class="burst"></i><i class="ring"></i>`,
  stonewall: () => n(4, (i) => `<i class="stone" style="--i:${i}"></i>`),
  lightning: () => `<svg viewBox="0 0 60 120"><path d="M34 0L10 64h18L18 120 52 46H32z"/></svg>`,
  flurry: () => n(3, (i) => `<i class="slash" style="--i:${i}"></i>`),
  afterimage: () => n(2, (i) => `<i class="ghost" style="--i:${i}"></i>`),
  charge: () => `<i class="dust"></i><i class="ring"></i>`,
  shockwave: () => n(3, (i) => `<i class="wave" style="--i:${i}"></i>`),
  breath: () => n(6, (i) => `<i class="mote" style="--i:${i}"></i>`),
  shadowclaw: () => n(3, (i) => `<i class="claw" style="--i:${i}"></i>`),
  swarm: () => n(9, (i) => `<i class="bat" style="--i:${i}"></i>`),
  nightveil: () => `<i class="veil"></i>${n(5, (i) => `<i class="twinkle" style="--i:${i}"></i>`)}`,
  thorns: () => n(4, (i) => `<i class="thorn" style="--i:${i}"></i>`),
  leafstorm: () => n(8, (i) => `<i class="leaf" style="--i:${i}"></i>`),
  roots: () => n(5, (i) => `<i class="root" style="--i:${i}"></i>`),
  special: () => `<i class="nova"></i>${n(8, (i) => `<i class="ray" style="--i:${i}"></i>`)}`,
};
