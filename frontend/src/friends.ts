/**
 * « Amis » (in the Familier tab): add a friend by user name, accept or decline requests, see my friends' familiers
 * and our record, challenge them to a friendly battle (normal or balanced), block someone. Friends never see my
 * activities, tracks or towns: only my user name and familiers.
 *
 * `watchChallenges`: every few seconds, a challenge received shows as a toast (Accept / Decline), and a battle
 * that starts (a challenge accepted) opens the arena.
 */
import { apiFetch } from "./api";
import type { BattleView } from "./battle";
import { escape } from "./format";
import { petArt } from "./pet-art";
import { pickTeam } from "./team-picker";

interface FriendPet {
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
  rarity: string | null;
}

interface Friend {
  name: string;
  record: { wins: number; losses: number; draws: number };
  pets: FriendPet[];
}

interface Challenge {
  id: number;
  from: string;
  to: string;
  mode: "normal" | "balanced";
  team: boolean;
  expires: string;
}

interface Inbox {
  incoming: Challenge[];
  outgoing: Challenge[];
  running: number | null;
}

interface FriendsState {
  friends: Friend[];
  incoming: string[];
  outgoing: string[];
  blocked: string[];
  pvp: Inbox;
}

const art = (p: FriendPet, size: number) => petArt({ species: p.species, stage: p.stage.index, branch: p.branch, color: p.color, type: p.type }, size);
const MODE = { normal: "normal", balanced: "équilibré" };
const label = (c: Challenge) => `${c.team ? "3 contre 3" : "1 contre 1"}, ${MODE[c.mode]}`;

/** Take up a challenge (in 3 against 3, with the team I choose). */
async function acceptChallenge(c: Challenge, battle: BattleView): Promise<string | null> {
  let pets: number[] | undefined;
  if (c.team) {
    const chosen = await pickTeam(`Ton équipe contre ${c.from}`);
    if (!chosen) return "";
    pets = chosen;
  }
  const err = await post(`/api/game/pvp/${c.id}/accept`, { pets: pets ?? [] });
  if (!err) battle.openPvp(c.id);
  return err;
}

async function post(url: string, body?: object, method = "POST"): Promise<string | null> {
  const r = await apiFetch(url, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (r.ok) return null;
  return (await r.json().catch(() => ({}))).detail ?? `erreur ${r.status}`;
}

export class FriendsView {
  constructor(private battle: BattleView) {}

  async render(box: HTMLElement, header: string, bind: () => void) {
    const r = await apiFetch("/api/game/friends");
    if (!r.ok) {
      box.innerHTML = `${header}<p class="status error">Amis indisponibles (${r.status}).</p>`;
      return bind();
    }
    const s = (await r.json()) as FriendsState;
    const again = () => this.render(box, header, bind);
    box.innerHTML = `${header}
      <form class="add-friend"><label for="add-friend-name">Ajouter un ami</label>
        <input id="add-friend-name" name="username" placeholder="Son identifiant, par exemple ethan" autocomplete="off" autocapitalize="none"
          spellcheck="false" required minlength="3" maxlength="32" />
        <button type="submit" class="primary">Envoyer la demande</button></form>
      <p id="friends-status" class="status" hidden></p>
      ${s.pvp.running ? `<button type="button" class="primary resume-pvp">Reprendre le combat amical en cours</button>` : ""}
      ${s.pvp.incoming.length ? `<h3>Défis reçus</h3><ul class="friend-rows">${s.pvp.incoming
        .map((c) => `<li><span><strong>${escape(c.from)}</strong> te défie <span class="muted small">(${label(c)})</span></span>
          <span><button type="button" class="primary" data-pvp-accept="${c.id}">Combattre</button> <button type="button" class="text-btn" data-pvp-decline="${c.id}">Refuser</button></span></li>`)
        .join("")}</ul>` : ""}
      ${s.pvp.outgoing.length ? `<h3>Défis envoyés</h3><ul class="friend-rows">${s.pvp.outgoing
        .map((c) => `<li><span>En attente de <strong>${escape(c.to)}</strong> <span class="muted small">(${label(c)}, 5 min)</span></span>
          <button type="button" class="text-btn" data-pvp-decline="${c.id}">Annuler</button></li>`)
        .join("")}</ul>` : ""}
      ${s.incoming.length ? `<h3>Demandes d'amis</h3><ul class="friend-rows">${s.incoming
        .map((n) => `<li><strong>${escape(n)}</strong><span><button type="button" class="primary" data-accept="${escape(n)}">Accepter</button>
          <button type="button" class="text-btn" data-decline="${escape(n)}">Refuser</button> <button type="button" class="text-btn" data-block="${escape(n)}">Bloquer</button></span></li>`)
        .join("")}</ul>` : ""}
      ${s.outgoing.length ? `<p class="muted small">Demandes envoyées : ${s.outgoing.map((n) => `${escape(n)} <button type="button" class="text-btn" data-remove="${escape(n)}">annuler</button>`).join(", ")}</p>` : ""}
      <h3>Mes amis</h3>
      ${s.friends.length ? `<div class="friends">${s.friends.map((f) => this.card(f)).join("")}</div>`
        : `<p class="muted small">Pas encore d'ami : ajoute-en un avec son identifiant. Il ne verra que ton identifiant et tes familiers, jamais tes sorties.</p>`}
      ${s.blocked.length ? `<p class="muted small">Bloqués : ${s.blocked.map((n) => `${escape(n)} <button type="button" class="text-btn" data-unblock="${escape(n)}">débloquer</button>`).join(", ")}</p>` : ""}`;
    bind();

    const status = (text: string | null) => {
      const el = box.querySelector<HTMLElement>("#friends-status")!;
      el.hidden = !text;
      el.textContent = text ?? "";
      el.classList.add("error");
    };
    const act = (sel: string, fn: (v: string) => Promise<string | null>) =>
      box.querySelectorAll<HTMLButtonElement>(`[${sel}]`).forEach((b) =>
        b.addEventListener("click", async () => {
          b.disabled = true;
          const err = await fn(b.getAttribute(sel)!);
          if (err) return status(err);
          again();
        }),
      );
    box.querySelector<HTMLFormElement>(".add-friend")!.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = (e.target as HTMLFormElement).username as HTMLInputElement;
      const err = await post("/api/game/friends", { username: input.value.trim().toLowerCase() });
      if (err) return status(err);
      again();
    });
    act("data-accept", (n) => post(`/api/game/friends/${encodeURIComponent(n)}/accept`));
    act("data-decline", (n) => post(`/api/game/friends/${encodeURIComponent(n)}/decline`));
    act("data-remove", (n) => post(`/api/game/friends/${encodeURIComponent(n)}`, undefined, "DELETE"));
    act("data-unblock", (n) => post(`/api/game/friends/${encodeURIComponent(n)}/block`, undefined, "DELETE"));
    act("data-block", async (n) => (confirm(`Bloquer ${n} ? Il ne pourra plus te demander en ami.`) ? post(`/api/game/friends/${encodeURIComponent(n)}/block`) : ""));
    act("data-unfriend", async (n) => (confirm(`Retirer ${n} de tes amis ?`) ? post(`/api/game/friends/${encodeURIComponent(n)}`, undefined, "DELETE") : ""));
    act("data-pvp-decline", (id) => post(`/api/game/pvp/${id}/decline`));
    act("data-pvp-accept", (id) => acceptChallenge(s.pvp.incoming.find((c) => c.id === Number(id))!, this.battle));
    box.querySelectorAll<HTMLButtonElement>("[data-challenge]").forEach((b) =>
      b.addEventListener("click", async () => {
        const card = b.closest<HTMLElement>(".friend")!;
        const mode = card.querySelector<HTMLSelectElement>(".pvp-mode")!.value as "normal" | "balanced";
        const team = card.querySelector<HTMLSelectElement>(".pvp-format")!.value === "3";
        let pets: number[] = [];
        if (team) {
          const chosen = await pickTeam(`Ton équipe contre ${b.dataset.challenge}`);
          if (!chosen) return;
          pets = chosen;
        }
        const err = await post("/api/game/pvp", { friend: b.dataset.challenge, mode, team, pets });
        if (err) return status(err);
        again();
      }),
    );
    box.querySelector(".resume-pvp")?.addEventListener("click", () => this.battle.openPvp(s.pvp.running!));
  }

  private card(f: Friend): string {
    const active = f.pets.find((p) => p.active) ?? f.pets[0];
    const r = f.record;
    return `<article class="friend">
      <div class="friend-art">${active ? art(active, 84) : ""}</div>
      <div class="friend-text">
        <div><strong>${escape(f.name)}</strong> <span class="muted small">${r.wins} V · ${r.losses} D${r.draws ? ` · ${r.draws} N` : ""}</span></div>
        ${active ? `<span class="small">${escape(active.name)} · ${escape(active.form)} · niv. ${active.level} <span class="type-badge t-${active.type}">${escape(active.type_name)}</span></span>` : `<span class="muted small">Pas encore de familier</span>`}
        <div class="friend-pets">${f.pets.filter((p) => p !== active).map((p) => `<span title="${escape(p.name)} · niv. ${p.level}">${art(p, 34)}</span>`).join("")}</div>
        <div class="friend-actions">
          <select class="pvp-format" aria-label="Format"><option value="1">1 contre 1</option><option value="3">3 contre 3</option></select>
          <select class="pvp-mode" aria-label="Niveaux"><option value="normal">Niveaux réels</option><option value="balanced">Équilibré</option></select>
          <button type="button" class="primary" data-challenge="${escape(f.name)}" ${active ? "" : "disabled"}>Défier</button>
          <button type="button" class="text-btn" data-unfriend="${escape(f.name)}">Retirer</button>
        </div>
      </div></article>`;
  }
}

/** Challenges received, wherever I am in the app: a toast; a battle that starts: the arena. */
export function watchChallenges(battle: BattleView) {
  const seen = new Set<number>();
  const toast = document.createElement("div");
  toast.className = "challenge-toast";
  toast.hidden = true;
  document.body.appendChild(toast);

  const tick = async () => {
    try {
      const r = await apiFetch("/api/game/pvp");
      if (r.ok) {
        const inbox = (await r.json()) as Inbox;
        if (inbox.running && !battle.isOpen) battle.openPvp(inbox.running);
        const c = inbox.incoming.find((x) => !seen.has(x.id));
        if (c && !battle.isOpen) {
          seen.add(c.id);
          toast.innerHTML = `<span>⚔ <strong>${escape(c.from)}</strong> te défie en combat amical (${label(c)})</span>
            <span><button type="button" class="primary yes">Combattre</button><button type="button" class="text-btn no">Refuser</button></span>`;
          toast.hidden = false;
          toast.querySelector(".yes")!.addEventListener("click", async () => {
            toast.hidden = true;
            const err = await acceptChallenge(c, battle);
            if (err) alert(err);
          });
          toast.querySelector(".no")!.addEventListener("click", async () => {
            toast.hidden = true;
            await post(`/api/game/pvp/${c.id}/decline`);
          });
        }
      }
    } catch {
      // offline for a moment: next time
    }
    setTimeout(tick, document.hidden ? 20000 : 6000);
  };
  tick();
}
