"""Familiers: the starter chosen once, levels bought with points up to the stage's max level, evolutions bought
at that max level, the final form's branch chosen by the running profile, one active familier per account.

Every purchase runs in one transaction with its spending (wallet.apply): the pet changes only if the points
were taken, and a retried request (same request_id) changes nothing.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from .config import STATS, GameConfig, Species
from .db import GameDB
from .wallet import Wallet, now_iso

NAME_MAX = 24


class GameError(Exception):
    """A refused action: `status` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class Pet:
    id: int
    user: str
    species: str
    name: str
    stage: int
    level: int
    branch: str | None
    active: bool
    origin: str
    acquired_at: str
    profile_since: str | None
    evolved_at: str | None


_COLUMNS = "id, user, species, name, stage, level, branch, active, origin, acquired_at, profile_since, evolved_at"


def _pet(row) -> Pet:
    return Pet(*row[:7], bool(row[7]), *row[8:])


def profile_metrics(activities: list[dict]) -> dict:
    """Shares and ratios of a running profile (activities_done rows), for the branches (config.METRICS)."""
    run = sum(a["run_m"] for a in activities)
    km = run / 1000
    return {
        "km": round(km, 1),
        "ascent_per_km": sum(a["ascent_m"] for a in activities) / km if km else 0.0,
        "night_share": sum(a["night_m"] for a in activities) / run if run else 0.0,
        "long_share": sum(a["run_m"] for a in activities if a["run_m"] >= 15000) / run if run else 0.0,
        "fast_share": sum(a["fast_m"] for a in activities) / run if run else 0.0,
        "new_share": sum(min(a["new_m"], a["run_m"]) for a in activities) / run if run else 0.0,
    }


class Pets:
    def __init__(self, db: GameDB, wallet: Wallet, cfg: GameConfig):
        self.db, self.wallet, self.cfg = db, wallet, cfg

    # --- reading ---

    def all(self, user: str) -> list[Pet]:
        return [_pet(r) for r in self.db.read(f"SELECT {_COLUMNS} FROM pets WHERE user = ? ORDER BY id", (user,))]

    def get(self, user: str, pet_id: int) -> Pet:
        rows = self.db.read(f"SELECT {_COLUMNS} FROM pets WHERE user = ? AND id = ?", (user, pet_id))
        if not rows:  # someone else's pet is as unknown as a pet that does not exist
            raise GameError("familier inconnu", 404)
        return _pet(rows[0])

    def active(self, user: str) -> Pet | None:
        rows = self.db.read(f"SELECT {_COLUMNS} FROM pets WHERE user = ? AND active = 1", (user,))
        return _pet(rows[0]) if rows else None

    def has_starter(self, user: str) -> bool:
        return bool(self.db.read("SELECT 1 FROM pets WHERE user = ? AND origin = 'starter'", (user,)))

    def species_of(self, pet: Pet) -> Species:
        return self.cfg.species[pet.species]

    def type_of(self, pet: Pet) -> str:
        sp = self.species_of(pet)
        branch = sp.branch(pet.branch)
        return branch.type if branch else sp.type

    def form_name(self, pet: Pet) -> str:
        sp = self.species_of(pet)
        branch = sp.branch(pet.branch)
        return branch.name if branch else sp.names[min(pet.stage, len(sp.names) - 1)]

    def stats(self, pet: Pet) -> dict[str, int]:
        return stats(self.cfg, self.species_of(pet), pet.stage, pet.level)

    # --- actions ---

    def choose_starter(self, user: str, species: str, name: str | None = None) -> Pet:
        """Once per account, for good; the starter becomes the active familier."""
        sp = self.cfg.species.get(species)
        if sp is None or not sp.starter:
            raise GameError("ce familier n'est pas un des trois de départ", 422)
        name = _clean_name(name) or sp.names[0].removeprefix("Œuf de ")
        with self.db.tx() as conn:
            if conn.execute("SELECT 1 FROM pets WHERE user = ? AND origin = 'starter'", (user,)).fetchone():
                raise GameError("le familier de départ est déjà choisi, et c'est définitif")
            conn.execute("UPDATE pets SET active = 0 WHERE user = ?", (user,))
            # profile_since NULL: the starter's running profile is the whole account's history
            cur = conn.execute("INSERT INTO pets (user, species, name, origin, active, acquired_at) VALUES (?, ?, ?, 'starter', 1, ?)",
                               (user, species, name, now_iso()))
            pet_id = cur.lastrowid
        return self.get(user, pet_id)

    def activate(self, user: str, pet_id: int) -> Pet:
        self.get(user, pet_id)
        with self.db.tx() as conn:
            conn.execute("UPDATE pets SET active = 0 WHERE user = ?", (user,))
            conn.execute("UPDATE pets SET active = 1 WHERE user = ? AND id = ?", (user, pet_id))
        return self.get(user, pet_id)

    def rename(self, user: str, pet_id: int, name: str) -> Pet:
        self.get(user, pet_id)
        if not (name := _clean_name(name)):
            raise GameError("un nom de 1 à 24 caractères", 422)
        with self.db.tx() as conn:
            conn.execute("UPDATE pets SET name = ? WHERE user = ? AND id = ?", (name, user, pet_id))
        return self.get(user, pet_id)

    def levels_affordable(self, pet: Pet, balance: int) -> int:
        """How many levels `balance` buys, up to the stage's max level."""
        cap = self.cfg.stages[pet.stage].max_level
        n, cost = 0, 0
        while pet.level + n < cap and cost + self.cfg.level_cost(pet.level + n + 1) <= balance:
            n += 1
            cost += self.cfg.level_cost(pet.level + n)
        return n

    def buy_levels(self, user: str, pet_id: int, count: int | str, request_id: str) -> tuple[Pet, int]:
        """Buy `count` levels ("max": as many as the points and the stage allow), all or nothing. Returns the
        pet and the points spent (0 for a retried request)."""
        key = f"levels:{request_id}"
        with self.db.tx() as conn:
            pet = self._get_in(conn, user, pet_id)
            if self.wallet.has_key(conn, user, key):
                return pet, 0
            cap = self.cfg.stages[pet.stage].max_level
            if pet.level >= cap:
                if pet.stage == self.cfg.final:
                    raise GameError(f"{pet.name} est au niveau maximum ({cap})")
                raise GameError(f"{pet.name} est au niveau max de son stade ({cap}) : fais-le évoluer pour monter plus haut")
            balance = self.wallet.balance_in(conn, user)
            n = self.levels_affordable(pet, balance) if count == "max" else int(count)
            if count == "max" and n == 0:
                raise GameError(f"points insuffisants : {self.cfg.level_cost(pet.level + 1)} nécessaires, solde de {balance}", 402)
            if n < 1:
                raise GameError("au moins un niveau", 422)
            if pet.level + n > cap:
                raise GameError(f"au plus {cap - pet.level} niveau(x) avant d'évoluer (niveau max du stade : {cap})")
            cost = self.cfg.levels_cost(pet.level, pet.level + n)
            target = pet.level + n
            self.wallet.apply(conn, user, {"key": key, "amount": -cost, "kind": "level", "date": now_iso(),
                                           "label": f"{pet.name} : niveau {target}", "detail": {"pet": pet.id, "from": pet.level, "to": target}})
            conn.execute("UPDATE pets SET level = ? WHERE id = ?", (target, pet.id))
        return self.get(user, pet_id), cost

    def evolve(self, user: str, pet_id: int, request_id: str, activities: Callable[[str | None], list[dict]]) -> tuple[Pet, int]:
        """At the stage's max level: the next stage, for its evolve_cost. The final form takes the branch that
        best matches the running profile since the pet arrived (`activities(since)`: activities_done rows)."""
        key = f"evolve:{request_id}"
        with self.db.tx() as conn:
            pet = self._get_in(conn, user, pet_id)
            if self.wallet.has_key(conn, user, key):
                return pet, 0
            if pet.stage >= self.cfg.final:
                raise GameError(f"{pet.name} a déjà atteint sa forme finale")
            cap = self.cfg.stages[pet.stage].max_level
            if pet.level < cap:
                raise GameError(f"{pet.name} doit d'abord atteindre le niveau {cap} pour évoluer")
            nxt = self.cfg.stages[pet.stage + 1]
            branch = None
            if nxt.index == self.cfg.final:
                branch = choose_branch(self.species_of(pet), profile_metrics(activities(pet.profile_since))).id
            self.wallet.apply(conn, user, {"key": key, "amount": -nxt.evolve_cost, "kind": "evolve", "date": now_iso(),
                                           "label": f"{pet.name} : {nxt.name.lower()}", "detail": {"pet": pet.id, "stage": nxt.id, "branch": branch}})
            conn.execute("UPDATE pets SET stage = ?, branch = ?, evolved_at = ? WHERE id = ?", (nxt.index, branch, now_iso(), pet.id))
        return self.get(user, pet_id), nxt.evolve_cost

    def _get_in(self, conn: sqlite3.Connection, user: str, pet_id: int) -> Pet:
        row = conn.execute(f"SELECT {_COLUMNS} FROM pets WHERE user = ? AND id = ?", (user, pet_id)).fetchone()
        if row is None:
            raise GameError("familier inconnu", 404)
        return _pet(row)


def stats(cfg: GameConfig, sp: Species, stage: int, level: int) -> dict[str, int]:
    """Base of the species x stage multiplier x level bonus."""
    k = cfg.stages[stage].stat_multiplier * (1 + cfg.stat_bonus_per_level * (level - 1))
    return {s: max(1, round(sp.base[s] * k)) for s in STATS}


def branch_scores(sp: Species, metrics: dict) -> list[tuple[str, float]]:
    return [(b.id, metrics.get(b.metric, 0.0) / b.reference) for b in sp.branches]


def choose_branch(sp: Species, metrics: dict):
    """The branch with the highest metric / reference (ties, or no running at all: the first one)."""
    scores = branch_scores(sp, metrics)
    best = max(range(len(scores)), key=lambda i: (scores[i][1], -i))
    return sp.branches[best]


def _clean_name(name: str | None) -> str:
    name = " ".join((name or "").split())
    return name if 0 < len(name) <= NAME_MAX else ""
