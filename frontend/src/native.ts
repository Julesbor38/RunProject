/**
 * The native iOS app (Capacitor, ios/): the page runs at capacitor://localhost, so the server is another origin.
 * - Its address is typed once at first launch and kept on the phone (nothing personal is built into the app,
 *   whose .ipa is public).
 * - The session is a token sent as `Authorization: Bearer` (iOS's web view blocks the server's cookie there).
 * In a browser and in the home-screen web app, nothing changes: relative paths and the session cookie.
 */
import { Capacitor } from "@capacitor/core";

const SERVER_KEY = "runproject.server";
const TOKEN_KEY = "runproject.token";

export const isNative = () => Capacitor.isNativePlatform();

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* not kept: asked again next launch */
  }
}

export const serverUrl = () => read(SERVER_KEY);

/** `/api/…` on the server (native app), or as is (web). */
export function apiUrl(path: string): string {
  return isNative() ? `${serverUrl() ?? ""}${path}` : path;
}

export function setSessionToken(token: string | null) {
  write(TOKEN_KEY, token);
}

/** Headers and credentials for API calls: the Bearer token in the native app, the cookie on the web. */
export function authInit(init: RequestInit = {}): RequestInit {
  if (!isNative()) return { credentials: "same-origin", ...init };
  const token = read(TOKEN_KEY);
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...init, credentials: "omit", headers };
}

export function authHeader(): Record<string, string> {
  const token = isNative() ? read(TOKEN_KEY) : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** « jules-laptop.tailf52fab.ts.net » or a pasted app URL -> https://jules-laptop.tailf52fab.ts.net */
export function normalizeServer(input: string): string {
  let url = input.trim();
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
  const u = new URL(url);
  return `${u.protocol}//${u.host}`;
}

async function reachable(server: string): Promise<boolean> {
  const abort = new AbortController(); // (AbortSignal.timeout needs iOS 16; the app supports iOS 15)
  const timer = setTimeout(() => abort.abort(), 8000);
  try {
    const r = await fetch(`${server}/api/health`, { cache: "no-store", signal: abort.signal });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Native app only: resolves once the server answers. First launch: asks for its address. Not reachable
 * (Tailscale off on the phone, PC asleep…): says so, with « Réessayer » and the address to change.
 */
export async function ensureServer(): Promise<void> {
  if (!isNative()) return;
  const saved = serverUrl();
  if (saved && (await reachable(saved))) return;
  return new Promise((resolve) => {
    const screen = document.getElementById("server-setup")!;
    const form = screen.querySelector("form")!;
    const input = form.elements.namedItem("server") as HTMLInputElement;
    const error = screen.querySelector(".server-error") as HTMLElement;
    const intro = screen.querySelector(".server-intro") as HTMLElement;
    const button = form.querySelector("button[type=submit]") as HTMLButtonElement;
    input.value = saved ?? "";
    intro.textContent = saved
      ? "Le serveur ne répond pas."
      : "Adresse de votre serveur RunProject (elle reste sur ce téléphone).";
    if (saved) showError("Active Tailscale sur ton iPhone, puis touche « Réessayer ».");
    button.textContent = saved ? "Réessayer" : "Continuer";
    screen.hidden = false;
    form.onsubmit = async (e) => {
      e.preventDefault();
      let server: string;
      try {
        server = normalizeServer(input.value);
      } catch {
        return showError("Adresse invalide (exemple : mon-pc.tailnet.ts.net).");
      }
      button.disabled = true;
      error.hidden = true;
      const ok = await reachable(server);
      button.disabled = false;
      if (!ok) return showError("Serveur injoignable. Active Tailscale sur ton iPhone et vérifie l'adresse.");
      if (server !== saved) setSessionToken(null); // another server: its own login
      write(SERVER_KEY, server);
      screen.hidden = true;
      resolve();
    };
    function showError(text: string) {
      error.textContent = text;
      error.hidden = false;
    }
  });
}
