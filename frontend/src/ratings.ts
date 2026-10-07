import { deleteRating, fetchRatings, saveRating } from "./api";
import type { ActivityFeature, Criterion, Rating } from "./api";
import { escape, formatDate, km } from "./format";

const STAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>`;

/** The user's ratings of their activities, and the sheet to rate one (1 to 5 per criterion). */
export class Ratings {
  criteria: Criterion[] = [];
  private byKey: Record<string, Rating> = {};
  private dialog = document.getElementById("rate-dialog") as HTMLDialogElement;
  private listeners: (() => void)[] = [];

  async load() {
    const data = await fetchRatings();
    this.criteria = data.criteria;
    this.byKey = data.ratings;
  }

  onChange(listener: () => void) {
    this.listeners.push(listener);
  }

  get(key: string): Rating | undefined {
    return this.byKey[key];
  }

  /** Mean of the scores given, or null when not rated. */
  average(key: string): number | null {
    const values = Object.values(this.byKey[key]?.scores ?? {});
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  }

  open(f: ActivityFeature) {
    const p = f.properties;
    const current = this.byKey[p.key];
    const scores: Record<string, number> = { ...(current?.scores ?? {}) };
    const form = this.dialog.querySelector("form")!;
    form.querySelector(".rate-title")!.textContent = p.name ?? "Sans nom";
    form.querySelector(".rate-meta")!.textContent = `${formatDate(p.start)} · ${km(p.distance_m)} · D+ ${p.ascent_m} m`;
    const comment = form.querySelector("textarea")!;
    comment.value = current?.comment ?? "";
    const error = form.querySelector(".rate-error") as HTMLElement;
    error.hidden = true;
    (form.querySelector(".rate-delete") as HTMLElement).hidden = !current;

    const rows = form.querySelector(".rate-rows")!;
    rows.innerHTML = this.criteria
      .map(
        (c) => `
        <div class="rate-row" data-key="${c.key}">
          <span>${escape(c.label)}</span>
          <div class="stars" role="radiogroup" aria-label="${escape(c.label)}">
            ${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-n="${n}" aria-label="${n} sur 5">${STAR}</button>`).join("")}
          </div>
        </div>`,
      )
      .join("");
    const paint = (row: Element) => {
      const v = scores[(row as HTMLElement).dataset.key!] ?? 0;
      row.querySelectorAll<HTMLButtonElement>(".stars button").forEach((b) => {
        const on = Number(b.dataset.n) <= v;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(Number(b.dataset.n) === v));
      });
    };
    rows.querySelectorAll(".rate-row").forEach((row) => {
      paint(row);
      row.querySelectorAll<HTMLButtonElement>(".stars button").forEach((b) =>
        b.addEventListener("click", () => {
          const key = (row as HTMLElement).dataset.key!;
          const n = Number(b.dataset.n);
          if (scores[key] === n) delete scores[key]; // tap the same star again to clear
          else scores[key] = n;
          paint(row);
        }),
      );
    });

    form.onsubmit = async (e) => {
      e.preventDefault();
      if (!Object.keys(scores).length && !comment.value.trim()) {
        error.textContent = "Donnez au moins une note ou un commentaire.";
        error.hidden = false;
        return;
      }
      try {
        this.byKey[p.key] = await saveRating(p.key, scores, comment.value);
        this.dialog.close();
        this.changed();
      } catch (err) {
        error.textContent = (err as Error).message;
        error.hidden = false;
      }
    };
    (form.querySelector(".rate-delete") as HTMLButtonElement).onclick = async () => {
      try {
        await deleteRating(p.key);
        delete this.byKey[p.key];
        this.dialog.close();
        this.changed();
      } catch (err) {
        error.textContent = (err as Error).message;
        error.hidden = false;
      }
    };
    (form.querySelector(".rate-close") as HTMLButtonElement).onclick = () => this.dialog.close();
    this.dialog.showModal();
  }

  private changed() {
    this.listeners.forEach((l) => l());
  }
}
