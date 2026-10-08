"""Battles of an account: the trail of levels (the next one opens when a level is won), the battle in progress
(one at a time, kept after each turn so it resumes when the app is reopened), and the rewards of victories.
The combat itself is combat.py."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from . import combat
from .config import GameConfig
from .db import GameDB
from .pets import GameError, Pets
from .wallet import Wallet, now_iso

PREVIEW_LEVELS = 12  # levels shown ahead on the trail


class Battles:
    def __init__(self, db: GameDB, wallet: Wallet, pets: Pets, cfg: GameConfig):
        self.db, self.wallet, self.pets, self.cfg = db, wallet, pets, cfg
        self.bc = combat.default(cfg)

    def cleared(self, user: str) -> int:
        rows = self.db.read("SELECT cleared FROM battle_progress WHERE user = ?", (user,))
        return rows[0][0] if rows else 0

    def rewarded_today(self, user: str) -> int:
        today = datetime.now(timezone.utc).isoformat()[:10]
        return self.db.read("SELECT count(*) FROM battles WHERE user = ? AND reward > 0 AND substr(finished_at, 1, 10) = ?", (user, today))[0][0]

    def running(self, user: str) -> int | None:
        rows = self.db.read("SELECT id FROM battles WHERE user = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (user,))
        return rows[0][0] if rows else None

    def level_preview(self, user: str, level: int) -> dict:
        cleared = self.cleared(user)
        enemies = combat.enemies_for(self.cfg, self.bc, level)
        return {"level": level, "kind": combat.level_kind(level), "open": level <= cleared + 1, "won": level <= cleared,
                "reward": combat.reward_for(self.bc, level, first=level > cleared),
                "enemies": [combat.fighter_view(self.cfg, self.bc, e) for e in enemies]}

    def trail(self, user: str) -> dict:
        cleared = self.cleared(user)
        first = max(1, cleared - 2)
        return {"cleared": cleared, "running": self.running(user),
                "daily": {"rewarded": self.rewarded_today(user), "limit": self.bc.p["daily_rewarded"]},
                "levels": [self.level_preview(user, n) for n in range(first, cleared + PREVIEW_LEVELS)]}

    def start(self, user: str, level: int) -> tuple[int, combat.Battle]:
        """A new battle on an open level, with the active familier (a battle in progress is given up)."""
        if level < 1 or level > self.cleared(user) + 1:
            raise GameError(f"niveau {level} pas encore ouvert : gagne d'abord le niveau {self.cleared(user) + 1}", 409)
        pet = self.pets.active(user)
        if pet is None:
            raise GameError("adopte d'abord un familier", 409)
        if pet.stage == 0:
            raise GameError(f"{pet.name} est encore un œuf : fais-le éclore pour combattre", 409)
        player = combat.player_fighter(self.cfg, self.bc, pet, self.pets.stats(pet), self.pets.type_of(pet), self.pets.form_name(pet))
        battle = combat.new_battle(self.cfg, self.bc, level, player, secrets.token_hex(8))
        state = json.dumps(battle.to_dict(), ensure_ascii=False)
        with self.db.tx() as conn:
            conn.execute("UPDATE battles SET status = 'fled', finished_at = ? WHERE user = ? AND status = 'running'", (now_iso(), user))
            bid = conn.execute("INSERT INTO battles (user, pet_id, level, seed, initial, state, status, created_at) VALUES (?,?,?,?,?,?,'running',?)",
                               (user, pet.id, level, battle.seed, state, state, now_iso())).lastrowid
        return bid, battle

    def get(self, user: str, battle_id: int) -> tuple[combat.Battle, dict]:
        rows = self.db.read("SELECT state, status, reward, level FROM battles WHERE user = ? AND id = ?", (user, battle_id))
        if not rows:
            raise GameError("combat inconnu", 404)
        state, status, reward, level = rows[0]
        return combat.Battle.from_dict(json.loads(state)), {"status": status, "reward": reward, "level": level}

    def turn(self, user: str, battle_id: int, move: str, target: str | None) -> tuple[combat.Battle, list[dict], int]:
        """One turn; at the end of a victory, the next level opens and the points come (within the daily limit)."""
        with self.db.tx() as conn:
            row = conn.execute("SELECT state, actions, status, level FROM battles WHERE user = ? AND id = ?", (user, battle_id)).fetchone()
            if row is None:
                raise GameError("combat inconnu", 404)
            if row[2] != "running":
                raise GameError("ce combat est terminé")
            battle = combat.Battle.from_dict(json.loads(row[0]))
            try:
                events = combat.play_turn(self.cfg, self.bc, battle, move, target)
            except combat.InvalidAction as e:
                raise GameError(str(e), 422) from e
            actions = json.loads(row[1]) + [[move, target]]
            reward = 0
            if battle.status != "running":
                level = row[3]
                if battle.status == "won":
                    cleared = conn.execute("SELECT cleared FROM battle_progress WHERE user = ?", (user,)).fetchone()
                    cleared = cleared[0] if cleared else 0
                    first = level > cleared
                    today = now_iso()[:10]
                    done_today = conn.execute("SELECT count(*) FROM battles WHERE user = ? AND reward > 0 AND substr(finished_at, 1, 10) = ?",
                                              (user, today)).fetchone()[0]
                    if done_today < self.bc.p["daily_rewarded"]:
                        reward = combat.reward_for(self.bc, level, first)
                        self.wallet.apply(conn, user, {"key": f"battle:{battle_id}", "amount": reward, "kind": "battle", "date": now_iso(),
                                                       "label": f"Victoire au niveau {level}", "detail": {"level": level, "first": first}})
                    if first:
                        conn.execute("INSERT INTO battle_progress (user, cleared) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET cleared = excluded.cleared",
                                     (user, level))
                    events.append({"t": "reward", "points": reward, "first": first, "limit": reward == 0})
            conn.execute("UPDATE battles SET state = ?, actions = ?, status = ?, reward = ?, finished_at = ? WHERE id = ?",
                         (json.dumps(battle.to_dict(), ensure_ascii=False), json.dumps(actions), battle.status, reward,
                          None if battle.status == "running" else now_iso(), battle_id))
        return battle, events, reward

    def flee(self, user: str, battle_id: int) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE battles SET status = 'fled', finished_at = ? WHERE user = ? AND id = ? AND status = 'running'",
                         (now_iso(), user, battle_id))

    def check_replay(self, user: str, battle_id: int) -> bool:
        """Does replaying the recorded moves from the initial state give the recorded state? (debugging)"""
        rows = self.db.read("SELECT initial, actions, state FROM battles WHERE user = ? AND id = ?", (user, battle_id))
        if not rows:
            raise GameError("combat inconnu", 404)
        initial, actions, state = rows[0]
        again = combat.replay(self.cfg, self.bc, json.loads(initial), [tuple(a) for a in json.loads(actions)])
        return again.to_dict() == json.loads(state)
