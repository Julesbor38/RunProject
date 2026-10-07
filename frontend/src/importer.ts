import { fetchImportStatus, uploadImport } from "./api";

export const NEW_KEY = "trailmap.newActivities"; // keys added by the last import, shown after the reload

/** "Mettre à jour mes données": upload a new Strava export or activity files, then reload with them. */
export function setupImporter() {
  const box = document.getElementById("import-box")!;
  const toggle = document.getElementById("import-toggle") as HTMLButtonElement;
  const input = box.querySelector("input[type=file]") as HTMLInputElement;
  const progress = box.querySelector(".import-progress") as HTMLElement;
  const bar = progress.querySelector(".track div") as HTMLElement;
  const label = progress.querySelector("span")!;
  const message = box.querySelector(".import-msg") as HTMLElement;

  toggle.addEventListener("click", () => openImporter(box.hidden === true));

  const show = (text: string, error = false) => {
    message.hidden = false;
    message.textContent = text;
    message.classList.toggle("error", error);
  };
  const setProgress = (fraction: number, text: string) => {
    progress.hidden = false;
    bar.style.width = `${Math.round(fraction * 100)}%`;
    label.textContent = text;
  };

  input.addEventListener("change", async () => {
    const files = [...(input.files ?? [])];
    if (!files.length) return;
    input.disabled = true;
    message.hidden = true;
    const size = files.reduce((s, f) => s + f.size, 0);
    try {
      setProgress(0, `Envoi de ${files.length > 1 ? `${files.length} fichiers` : files[0].name} (${(size / 2 ** 20).toFixed(0)} Mo)…`);
      await uploadImport(files, (f) => setProgress(f * 0.5, `Envoi… ${Math.round(f * 100)} %`));
      setProgress(0.6, "Lecture des sorties (jusqu'à une minute pour une archive complète)…");
      const status = await waitForImport();
      if (status.state === "error") throw new Error(status.message ?? "échec de l'import");
      const added = status.new ?? [];
      setProgress(1, "Terminé");
      if (!added.length) {
        show("Aucune nouvelle sortie : elles étaient toutes déjà importées.");
        return;
      }
      try {
        sessionStorage.setItem(NEW_KEY, JSON.stringify(added));
      } catch {
        /* the banner just won't show */
      }
      show(`${added.length} nouvelle${added.length > 1 ? "s" : ""} sortie${added.length > 1 ? "s" : ""} ajoutée${added.length > 1 ? "s" : ""}. Mise à jour de la carte…`);
      setTimeout(() => location.reload(), 1200);
    } catch (err) {
      show(`Import impossible : ${(err as Error).message}`, true);
      progress.hidden = true;
    } finally {
      input.disabled = false;
      input.value = "";
    }
  });
}

/** Show (or hide) the import box of the "Mes sorties" tab. */
export function openImporter(open = true) {
  document.getElementById("import-box")!.hidden = !open;
  document.getElementById("import-toggle")!.setAttribute("aria-expanded", String(open));
}

async function waitForImport() {
  for (;;) {
    const s = await fetchImportStatus();
    if (s.state !== "running") return s;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** Keys of the activities the last import added (once, right after its reload). */
export function takeNewActivities(): string[] {
  try {
    const keys = JSON.parse(sessionStorage.getItem(NEW_KEY) ?? "[]");
    return Array.isArray(keys) ? keys : [];
  } catch {
    return [];
  }
}

export function forgetNewActivities() {
  try {
    sessionStorage.removeItem(NEW_KEY);
  } catch {
    /* nothing to forget */
  }
}
