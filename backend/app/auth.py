"""Accounts and sessions: every /api route except /api/health and /api/auth/* needs a logged-in user.

- Accounts are created on the login page (POST /api/auth/signup, unless TRAILMAP_SIGNUP=0, e.g. on a
  public server) or from the command line:
    python -m app.auth add-user <name>        (asks for the password)
    python -m app.auth passwd <name>
    python -m app.auth list | remove <name>
- Passwords are hashed with scrypt (salted, memory-hard), never stored or logged in clear.
- A session is a random token in an HttpOnly, Secure, SameSite=Strict cookie; the server keeps
  only its SHA-256, so a leaked sessions file does not let anyone log in.
- Repeated failures lock the account for that address for a while (brute force).
Files: <data>/auth/users.json and <data>/auth/sessions.json (data/ is never committed).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path

from fastapi import HTTPException

COOKIE = "trailmap_session"
SESSION_DAYS = 30
MIN_PASSWORD = 10
MAX_FAILURES = 5  # then locked for LOCK_S
LOCK_S = 15 * 60
SCRYPT = {"n": 2**15, "r": 8, "p": 1}  # ~0.1 s per hash, 32 MB
SIGNUP_OPEN = os.environ.get("TRAILMAP_SIGNUP", "1") != "0"
MAX_SIGNUPS = 5  # per client address and hour
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")  # also the name of the user's data folder

_lock = threading.Lock()
_failures: dict[tuple[str, str], list[float]] = {}  # (user, client address) -> failure times
_signups: dict[str, list[float]] = {}  # client address -> sign-up times


def _dir(data_dir: Path) -> Path:
    return data_dir / "auth"


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


# --- passwords ---


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=64 * 2**20, **SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        **SCRYPT, salt=base64.b64encode(salt).decode(), digest=base64.b64encode(digest).decode()
    )


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=64 * 2**20)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except ValueError:
        return False


_DUMMY = hash_password(secrets.token_hex(8))  # unknown users take as long as known ones


def users(data_dir: Path) -> dict:
    return _read(_dir(data_dir) / "users.json")


def normalize(name: str) -> str:
    return name.strip().lower()


def check_new_account(name: str, password: str) -> None:
    if not USERNAME.match(name):
        raise ValueError("identifiant : 3 à 32 caractères, lettres minuscules, chiffres, « . », « _ » ou « - »")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"mot de passe trop court ({MIN_PASSWORD} caractères minimum)")


def create_user(data_dir: Path, name: str, password: str, client: str) -> str:
    """Sign-up from the page: a new account (ValueError if invalid or taken), limited per address."""
    name = normalize(name)
    check_new_account(name, password)
    with _lock:
        recent = [t for t in _signups.get(client, []) if t > time.time() - 3600]
        if len(recent) >= MAX_SIGNUPS:
            raise HTTPException(429, "trop de comptes créés : réessayez dans une heure")
        _signups[client] = [*recent, time.time()]
    set_password(data_dir, name, password, new=True)
    return name


def set_password(data_dir: Path, name: str, password: str, new: bool = False) -> None:
    """Set a password; `new`: create the account, which must not exist yet (ValueError)."""
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"mot de passe trop court ({MIN_PASSWORD} caractères minimum)")
    with _lock:
        all_users = users(data_dir)
        if new and name in all_users:
            raise ValueError("cet identifiant est déjà pris")
        all_users[name] = {"password": hash_password(password), "created": all_users.get(name, {}).get("created", int(time.time()))}
        _write(_dir(data_dir) / "users.json", all_users)
        # A new password ends that user's other sessions.
        sessions = _sessions(data_dir)
        _write(_dir(data_dir) / "sessions.json", {k: v for k, v in sessions.items() if v["user"] != name})


def remove_user(data_dir: Path, name: str) -> bool:
    with _lock:
        all_users = users(data_dir)
        if all_users.pop(name, None) is None:
            return False
        _write(_dir(data_dir) / "users.json", all_users)
        _write(_dir(data_dir) / "sessions.json", {k: v for k, v in _sessions(data_dir).items() if v["user"] != name})
        return True


# --- sessions ---


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _sessions(data_dir: Path) -> dict:
    now = time.time()
    return {k: v for k, v in _read(_dir(data_dir) / "sessions.json").items() if v["expires"] > now}


def new_session(data_dir: Path, name: str) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        sessions = _sessions(data_dir)
        sessions[_token_id(token)] = {"user": name, "expires": time.time() + SESSION_DAYS * 86400}
        _write(_dir(data_dir) / "sessions.json", sessions)
    return token


def login(data_dir: Path, name: str, password: str, client: str) -> str:
    """A new session token, or HTTPException 401 / 429."""
    name = normalize(name)
    key = (name, client)
    with _lock:
        recent = [t for t in _failures.get(key, []) if t > time.time() - LOCK_S]
        _failures[key] = recent
        if len(recent) >= MAX_FAILURES:
            raise HTTPException(429, "trop d'essais : réessayez dans 15 minutes")
    user = users(data_dir).get(name)
    if not check_password(password, user["password"] if user else _DUMMY) or not user:
        with _lock:
            _failures.setdefault(key, []).append(time.time())
        raise HTTPException(401, "identifiant ou mot de passe incorrect")
    with _lock:
        _failures.pop(key, None)
    return new_session(data_dir, name)


def logout(data_dir: Path, token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _sessions(data_dir)
        if sessions.pop(_token_id(token), None):
            _write(_dir(data_dir) / "sessions.json", sessions)


def session_user(data_dir: Path, token: str | None) -> str | None:
    if not token:
        return None
    s = _sessions(data_dir).get(_token_id(token))
    return s["user"] if s and s["user"] in users(data_dir) else None


# --- command line ---


def main() -> None:
    from .api import DATA_DIR

    parser = argparse.ArgumentParser(description="Trail Map accounts")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("add-user", "passwd", "remove"):
        sub.add_parser(cmd).add_argument("name")
    sub.add_parser("list")
    args = parser.parse_args()
    if args.cmd == "list":
        for name in users(DATA_DIR):
            print(name)
    elif args.cmd == "remove":
        print("supprimé" if remove_user(DATA_DIR, args.name) else "compte inconnu")
    else:
        args.name = normalize(args.name)
        if args.cmd == "add-user" and args.name in users(DATA_DIR):
            sys.exit("ce compte existe déjà (passwd pour changer son mot de passe)")
        if args.cmd == "add-user" and not USERNAME.match(args.name):
            sys.exit("identifiant : 3 à 32 caractères, lettres minuscules, chiffres, « . », « _ » ou « - »")
        if args.cmd == "passwd" and args.name not in users(DATA_DIR):
            sys.exit("compte inconnu")
        password = getpass.getpass("Mot de passe : ")
        if password != getpass.getpass("Encore une fois : "):
            sys.exit("les deux mots de passe diffèrent")
        try:
            set_password(DATA_DIR, args.name, password)
        except ValueError as e:
            sys.exit(str(e))
        print(f"compte « {args.name} » prêt")


if __name__ == "__main__":
    main()
