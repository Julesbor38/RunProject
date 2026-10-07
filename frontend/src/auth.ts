import { currentUser, login, logout, setUnauthorizedHandler, signup, signupOpen } from "./api";

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
    const button = form.querySelector("button[type=submit]") as HTMLButtonElement;
    const password = form.elements.namedItem("password") as HTMLInputElement;
    const setMode = (mode: "login" | "signup") => {
      form.dataset.mode = mode;
      password.autocomplete = mode === "signup" ? "new-password" : "current-password";
      error.hidden = true;
    };
    screen.hidden = false;
    setMode("login");
    (form.elements.namedItem("username") as HTMLInputElement).focus();
    signupOpen().then((open) => ((form.querySelector(".switch-mode") as HTMLElement).hidden = !open));
    form.querySelectorAll<HTMLButtonElement>(".switch-mode button").forEach((b) => (b.onclick = () => setMode(b.dataset.to as "login" | "signup")));
    form.onsubmit = async (e) => {
      e.preventDefault();
      const data = new FormData(form);
      const username = String(data.get("username") ?? "").trim();
      const creating = form.dataset.mode === "signup";
      error.hidden = true;
      if (creating && data.get("password") !== data.get("confirm")) {
        error.textContent = "Les deux mots de passe diffèrent.";
        error.hidden = false;
        return;
      }
      button.disabled = true;
      try {
        const user = await (creating ? signup : login)(username, String(data.get("password") ?? ""));
        screen.hidden = true;
        form.reset();
        pending = null;
        resolve(user);
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
