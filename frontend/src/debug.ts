/**
 * Debug panel for the phone (no Safari inspector without a Mac): open it with ?debug=1 or a long press
 * on the « Trail Map » title. It shows how the page runs (home-screen app or not, iOS version), what file
 * sharing accepts, and a journal of the last share attempts — kept in localStorage, since a stuck app
 * may have to be relaunched before one can read it.
 */
import { isNative, serverUrl } from "./native";
import { GPX_MIME_TYPES, shareableFile } from "./share";

const LOG_KEY = "trailmap.debugLog";
const MAX_LOG = 30;

let gpxChecks: { filename: string; checks: Record<string, string>; chosen: string | null } | null = null;

export function debugLog(event: string, detail = "") {
  try {
    const log = readLog();
    log.push({ at: new Date().toISOString(), event, detail });
    localStorage.setItem(LOG_KEY, JSON.stringify(log.slice(-MAX_LOG)));
  } catch {
    /* storage unavailable: nothing kept */
  }
  if (panel && !panel.hidden) render();
}

/** canShare results for the GPX of the route last prepared (set by share.ts). */
export function setGpxChecks(filename: string, checks: Record<string, string>, chosen: string | null) {
  gpxChecks = { filename, checks, chosen };
  if (panel && !panel.hidden) render();
}

function readLog(): { at: string; event: string; detail: string }[] {
  try {
    return JSON.parse(localStorage.getItem(LOG_KEY) ?? "[]");
  } catch {
    return [];
  }
}

let panel: HTMLElement | null = null;

export function setupDebug() {
  if (new URLSearchParams(location.search).get("debug") === "1") toggle(true);
  const title = document.querySelector(".panel-head h1") as HTMLElement;
  let timer = 0;
  const cancel = () => clearTimeout(timer);
  title.addEventListener("pointerdown", () => {
    cancel();
    timer = window.setTimeout(() => toggle(), 800);
  });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) title.addEventListener(ev, cancel);
  title.addEventListener("contextmenu", (e) => e.preventDefault()); // iOS: no callout on the long press
}

function toggle(open = !panel || panel.hidden) {
  if (!panel) {
    panel = document.createElement("section");
    panel.id = "debug-panel";
    document.body.appendChild(panel);
  }
  panel.hidden = !open;
  if (open) render();
}

function render() {
  if (!panel) return;
  const nav = navigator as Navigator & { standalone?: boolean };
  const test = shareableFile("<gpx/>", "test.gpx").checks;
  const rows: [string, string][] = [
    ["App native iOS (Capacitor)", String(isNative())],
    ["Serveur (app native)", serverUrl() ?? "—"],
    ["Mode écran d'accueil (navigator.standalone)", String(nav.standalone)],
    ["display-mode: standalone", String(matchMedia("(display-mode: standalone)").matches)],
    ["iOS", /OS (\d+[_\d]*) like Mac OS X/.exec(navigator.userAgent)?.[1]?.replace(/_/g, ".") ?? "?"],
    ["navigator.share", typeof navigator.share],
    ["navigator.canShare", typeof navigator.canShare],
    ...GPX_MIME_TYPES.map((t): [string, string] => [`canShare fichier test (${t})`, test[t]]),
    ...(gpxChecks
      ? [
          ["Dernier GPX préparé", gpxChecks.filename] as [string, string],
          ...GPX_MIME_TYPES.map((t): [string, string] => [`canShare ${t}`, gpxChecks!.checks[t]]),
          ["Type retenu", gpxChecks.chosen ?? "aucun : repli /dl"] as [string, string],
        ]
      : [["Dernier GPX préparé", "aucun (générez un itinéraire)"] as [string, string]]),
  ];
  const log = readLog().reverse();
  panel.innerHTML = `
    <header><strong>Debug</strong><button type="button" data-act="close" aria-label="Fermer">×</button></header>
    <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <p class="ua">${esc(navigator.userAgent)}</p>
    <div class="acts">
      <button type="button" data-act="test">Tester le partage (fichier test)</button>
      <button type="button" data-act="clear">Effacer le journal</button>
    </div>
    <h4>Journal (le plus récent d'abord)</h4>
    <ol>${log.map((l) => `<li><time>${esc(l.at.slice(11, 19))}</time> ${esc(l.event)} ${esc(l.detail)}</li>`).join("") || "<li>vide</li>"}</ol>`;
  panel.querySelector("[data-act=close]")!.addEventListener("click", () => toggle(false));
  panel.querySelector("[data-act=clear]")!.addEventListener("click", () => {
    try {
      localStorage.removeItem(LOG_KEY);
    } catch {
      /* nothing to clear */
    }
    render();
  });
  panel.querySelector("[data-act=test]")!.addEventListener("click", () => {
    // In the tap, nothing awaited: like the real button.
    const { file } = shareableFile(`<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Trail Map" xmlns="http://www.topografix.com/GPX/1/1"/>`, "test.gpx");
    if (!file) return debugLog("test", "aucun type accepté par canShare");
    debugLog("test : partage", file.type);
    navigator.share({ files: [file] }).then(
      () => debugLog("test", "terminé"),
      (e: Error) => debugLog("test : erreur", `${e.name}: ${e.message}`),
    );
  });
}

function esc(s: string) {
  return String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
