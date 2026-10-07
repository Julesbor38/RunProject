import { currentUser, login, logout, setUnauthorizedHandler } from "./api";

/**
 * Resolves with the user name once logged in: right away with a valid session cookie,
 * else after the login screen. A later 401 (session expired) shows it again, then reloads.
 */
export async function ensureLoggedIn(): Promise<string> {
  setUnauthorizedHandler(() => showLogin().then(() => location.reload()));
  const user = await currentUser().catch(() => null);
  return user ?? showLogin();
}

export async function signOut() {
  await logout();
  location.reload();
}

let pending: Promise<string> | null = null;

function showLogin(): Promise<string> {
  pending ??= new Promise<string>((resolve) => {
    const screen = document.getElementById("login")!;
    const form = screen.querySelector("form")!;
    const error = screen.querySelector(".login-error") as HTMLElement;
    const button = form.querySelector("button")!;
    screen.hidden = false;
    (form.elements.namedItem("username") as HTMLInputElement).focus();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const data = new FormData(form);
      const username = String(data.get("username") ?? "").trim();
      button.disabled = true;
      error.hidden = true;
      try {
        await login(username, String(data.get("password") ?? ""));
        screen.hidden = true;
        form.reset();
        pending = null;
        resolve(username);
      } catch (err) {
        error.textContent = (err as Error).message;
        error.hidden = false;
      } finally {
        button.disabled = false;
      }
    };
  });
  return pending;
}
