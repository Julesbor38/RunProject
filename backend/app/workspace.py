"""Each account's own data: data/users/<name>/ holds its activities (raw/, cache/), privacy zones,
ratings and generated routes; nobody else's requests ever read it. OSM tiles and elevation
(data/osm, data/dem) are shared: they hold no personal data.

Data from before accounts existed (data/raw, data/cache...) is handed to one account with:
    python -m app.workspace adopt <name>
"""
from __future__ import annotations

import argparse
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .routing import RoutingService
from .routing.job import Job

LEGACY_ITEMS = ["raw", "cache", "routes", "ratings.json", "privacy.json"]


def user_dir(data_dir: Path, user: str) -> Path:
    return data_dir / "users" / user


@dataclass
class Workspace:
    """One user's data in memory: activities, routing (their tracks make « déjà couru »), jobs, imports."""

    user: str
    dir: Path
    activities: dict
    routing: RoutingService
    jobs: dict[str, Job] = field(default_factory=dict)
    import_status: dict = field(default_factory=lambda: {"state": "idle"})
    import_lock: threading.Lock = field(default_factory=threading.Lock)


def adopt_legacy(data_dir: Path, user: str) -> list[str]:
    """Move the pre-accounts data into the user's folder. Returns what was moved.

    An item already in the user's folder is only replaced when it is an empty folder
    (created by a first login before the move), never overwritten otherwise.
    """
    dest = user_dir(data_dir, user)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in LEGACY_ITEMS:
        src, dst = data_dir / name, dest / name
        if not src.exists():
            continue
        if dst.exists():
            if dst.is_dir() and not any(dst.rglob("*.*")):
                shutil.rmtree(dst)
            else:
                raise FileExistsError(f"{dst} existe déjà : rien n'a été écrasé")
        shutil.move(src, dst)
        moved.append(name)
    return moved


def main() -> None:
    from .api import DATA_DIR
    from .auth import users

    parser = argparse.ArgumentParser(description="Per-account data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("adopt", help="give the pre-accounts data (data/raw...) to an account").add_argument("name")
    args = parser.parse_args()
    if args.name not in users(DATA_DIR):
        sys.exit("compte inconnu")
    try:
        moved = adopt_legacy(DATA_DIR, args.name)
    except FileExistsError as e:
        sys.exit(str(e))
    print(f"déplacé vers {user_dir(DATA_DIR, args.name)} : {', '.join(moved) or 'rien'}")
    print("redémarrer l'API pour qu'elle relise les données")


if __name__ == "__main__":
    main()
