/**
 * Credits earned by running (km, new paths and area, places, milestones and badges): the balance in the
 * panel's header, the details in the « Exploration » tab, and a « +N crédits » toast after an import, once
 * the new activities are analysed. Spending them comes later.
 */
import { apiFetch } from "./api";
import { escape, formatDate } from "./format";

interface Entry {
  key: string;
  amount: number;
  kind: "activity" | "area" | "poi" | "milestone" | "badge";
  label: string;
  date: string | null;
  detail: { run_m?: number; new_m?: number; area_m2?: number; kind?: string };
}

interface CreditsSummary {
  balance: number;
  welcome: number;
  history: number;
  welcome_cap: number;
  by_kind: Record<string, number>;
  new: number;
  entries: Entry[];
  rates: { km_run: number; km_new: number; km2_area: number; badge: number; milestones: Record<string, number> };
  running: boolean;
}

const nf = (n: number, digits = 0) => n.toLocaleString("fr-FR", { maximumFractionDigits: digits });
const km = (m: number) => nf(m / 1000, 1);
const KINDS: Record<string, string> = { activity: "Sorties", area: "Superficie", poi: "Lieux", milestone: "Paliers", badge: "Badges" };

export class Credits {
  private poll = 0;

  constructor(private onOpen: () => void) {
    document.getElementById("credits-chip")!.addEventListener("click", () => {
      this.onOpen();
      document.getElementById("credits")!.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  /** The balance (and, while the latest activities are being analysed, again in a few seconds). */
  async refresh() {
    clearTimeout(this.poll);
    const r = await apiFetch("/api/credits");
    if (!r.ok) return;
    const s = (await r.json()) as CreditsSummary;
    this.render(s);
    if (s.running) this.poll = window.setTimeout(() => this.refresh(), 4000);
    else if (s.new > 0) this.announce(s);
  }

  private render(s: CreditsSummary) {
    document.getElementById("credits-chip")!.hidden = false;
    document.getElementById("credits-balance")!.textContent = nf(s.balance);
    const box = document.getElementById("credits")!;
    box.hidden = false;
    const welcome = s.history
      ? `dont ${nf(s.welcome)} de bienvenue${s.history > s.welcome ? ` (votre historique en valait ${nf(s.history)}, plafonné à ${nf(s.welcome_cap)})` : ""}`
      : "";
    const kinds = Object.entries(s.by_kind)
      .map(([k, v]) => `<span>${KINDS[k] ?? k} <strong>+${nf(v)}</strong></span>`)
      .join("");
    const m = s.rates.milestones;
    box.innerHTML = `
      <div class="credits-head"><span class="spark" aria-hidden="true">✦</span>
        <div><strong>${nf(s.balance)}</strong> crédit${s.balance > 1 ? "s" : ""}<span class="muted small">${welcome}</span></div></div>
      ${kinds ? `<div class="credits-kinds">${kinds}</div>` : ""}
      <details class="credits-rules"><summary>Comment gagner des crédits</summary><ul>
        <li><strong>${nf(s.rates.km_run)}</strong> par km couru (sorties horodatées)</li>
        <li><strong>+${nf(s.rates.km_new)}</strong> par km de chemin jamais couru</li>
        <li><strong>${nf(s.rates.km2_area)}</strong> par km² de superficie découverte</li>
        <li>Lieux : <strong>10</strong> sommet ou cascade, <strong>5</strong> point de vue ou lac, <strong>3</strong> monument, <strong>1–2</strong> les autres</li>
        <li>Paliers d'une commune : ${Object.entries(m).map(([p, v]) => `${p} % → <strong>${v}</strong>`).join(", ")}</li>
        <li><strong>${nf(s.rates.badge)}</strong> par badge</li>
        <li>Vos sorties d'avant les crédits comptent dans un bonus de bienvenue (${nf(s.welcome_cap)} au plus).</li>
      </ul><p class="muted small">Bientôt : les dépenser dans l'app (itinéraires, collection…).</p></details>
      <h3>Derniers gains</h3>
      <ul class="credits-list">${
        s.entries.length
          ? s.entries.map(entry).join("")
          : `<li class="empty">Rien encore depuis le bonus de bienvenue : vos prochaines sorties rapporteront des crédits.</li>`
      }</ul>`;
  }

  private announce(s: CreditsSummary) {
    const box = document.getElementById("achievement-toast")!;
    box.innerHTML = `<span class="spark">✦</span><div><strong>+${nf(s.new)} crédit${s.new > 1 ? "s" : ""}</strong>
      <span>Solde : ${nf(s.balance)}</span></div>`;
    box.hidden = false;
    box.classList.remove("show");
    void box.offsetWidth; // restart the animation
    box.classList.add("show");
    setTimeout(() => (box.hidden = true), 5200);
    apiFetch("/api/explore/seen", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids: ["credits"] }),
    }).catch(() => {});
  }
}

function entry(e: Entry): string {
  let title = escape(e.label);
  let meta = "";
  if (e.kind === "activity") {
    title = `Sortie du ${formatDate(e.date)}`;
    const d = e.detail;
    meta = [`${km(d.run_m ?? 0)} km`, d.new_m ? `${km(d.new_m)} km nouveaux` : "", d.area_m2 ? `${nf((d.area_m2 ?? 0) / 1e6, 2)} km²` : ""]
      .filter(Boolean)
      .join(" · ");
  } else if (e.kind === "poi") meta = "Lieu découvert";
  else if (e.kind === "milestone") meta = "Palier";
  else if (e.kind === "badge") meta = "Badge";
  return `<li><div><span class="name">${title}</span><span class="meta">${meta}</span></div><strong class="amount">+${nf(e.amount)}</strong></li>`;
}
