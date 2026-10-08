"""Battles of an account: the trail of levels (the next one opens when a level is won), solo or with a team of
3 (a trail of its own), the battle in progress (one at a time, kept after each turn so it resumes when the app
is reopened), and the rewards of victories (shared by both trails). The combat itself is combat.py."""
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
TEAM_SIZE = 3


def team_fighters(cfg: GameConfig, bc, pets: Pets, user: str, pet_ids: list[int] | None, team: bool, side: str = "player",
                  prefix: str = "p", balanced=None) -> list[combat.Fighter]:
    """The fighters of an account: its active familier (solo), or the 3 familiers chosen (team); hatched ones only.
    `balanced(species)`: stats to use instead of the familier's own (a balanced friendly battle)."""
    if team:
        ids = list(dict.fromkeys(pet_ids or []))
        if len(ids) != TEAM_SIZE:
            raise GameError(f"choisis {TEAM_SIZE} familiers différents pour l'équipe", 422)
        chosen = [pets.get(user, i) for i in ids]
    else:
        pet = pets.active(user)
        if pet is None:
            raise GameError("adopte d'abord un familier", 409)
        chosen = [pet]
    out = []
    for n, pet in enumerate(chosen, 1):
        if pet.stage == 0:
            raise GameError(f"{pet.name} est encore un œuf : fais-le éclore pour combattre", 409)
        st = balanced(cfg.species[pet.species]) if balanced else pets.stats(pet)
        fid = f"{prefix}{n}" if team else (prefix if prefix == "p" else f"{prefix}1")
        out.append(combat.player_fighter(cfg, bc, pet, st, pets.type_of(pet), pets.form_name(pet), fid, side))
    return out


class Battles:
    def __init__(self, db: GameDB, wallet: Wallet, pets: Pets, cfg: GameConfig):
        self.db, self.wallet, self.pets, self.cfg = db, wallet, pets, cfg
        self.bc = combat.default(cfg)

    def cleared(self, user: str, team: bool = False) -> int:
        rows = self.db.read(f"SELECT {'team_cleared' if team else 'cleared'} FROM battle_progress WHERE user = ?", (user,))
        return rows[0][0] if rows else 0

    def rewarded_today(self, user: str) -> int:
        today = datetime.now(timezone.utc).isoformat()[:10]
        return self.db.read("SELECT count(*) FROM battles WHERE user = ? AND reward > 0 AND substr(finished_at, 1, 10) = ?", (user, today))[0][0]

    def running(self, user: str) -> int | None:
        rows = self.db.read("SELECT id FROM battles WHERE user = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (user,))
        return rows[0][0] if rows else None

    def level_preview(self, user: str, level: int, team: bool = False, cleared: int | None = None) -> dict:
        cleared = self.cleared(user, team) if cleared is None else cleared
        enemies = combat.enemies_for(self.cfg, self.bc, level, team)
        return {"level": level, "kind": combat.level_kind(level), "open": level <= cleared + 1, "won": level <= cleared,
                "reward": combat.reward_for(self.bc, level, first=level > cleared),
                "enemies": [combat.fighter_view(self.cfg, self.bc, e) for e in enemies]}

    def trail(self, user: str, team: bool = False) -> dict:
        cleared = self.cleared(user, team)
        first = max(1, cleared - 2)
        return {"team": team, "cleared": cleared, "running": self.running(user), "team_size": TEAM_SIZE,
                "daily": {"rewarded": self.rewarded_today(user), "limit": self.bc.p["daily_rewarded"]},
                "levels": [self.level_preview(user, n, team, cleared) for n in range(first, cleared + PREVIEW_LEVELS)]}

    def start(self, user: str, level: int, team: bool = False, pet_ids: list[int] | None = None) -> tuple[int, combat.Battle]:
        """A new battle on an open level of the trail, with the active familier (solo) or the 3 chosen (team); a
        battle in progress is given up."""
        cleared = self.cleared(user, team)
        if level < 1 or level > cleared + 1:
            raise GameError(f"niveau {level} pas encore ouvert : gagne d'abord le niveau {cleared + 1}", 409)
        players = team_fighters(self.cfg, self.bc, self.pets, user, pet_ids, team)
        battle = combat.new_battle(self.cfg, self.bc, level, players, secrets.token_hex(8), team)
        state = json.dumps(battle.to_dict(), ensure_ascii=False)
        pet_id = (pet_ids or [None])[0] if team else self.pets.active(user).id
        with self.db.tx() as conn:
            conn.execute("UPDATE battles SET status = 'fled', finished_at = ? WHERE user = ? AND status = 'running'", (now_iso(), user))
            bid = conn.execute("INSERT INTO battles (user, pet_id, level, seed, initial, state, status, team, created_at) VALUES (?,?,?,?,?,?,'running',?,?)",
                               (user, pet_id, level, battle.seed, state, state, int(team), now_iso())).lastrowid
        return bid, battle

    def get(self, user: str, battle_id: int) -> tuple[combat.Battle, dict]:
        rows = self.db.read("SELECT state, status, reward, level, team FROM battles WHERE user = ? AND id = ?", (user, battle_id))
        if not rows:
            raise GameError("combat inconnu", 404)
        state, status, reward, level, team = rows[0]
        return combat.Battle.from_dict(json.loads(state)), {"status": status, "reward": reward, "level": level, "team": bool(team)}

    def turn(self, user: str, battle_id: int, choices: dict[str, tuple[str, str | None]]) -> tuple[combat.Battle, list[dict], int]:
        """One turn (`choices`: a move, and a target, for each of my fighters; the AI plays those left out); at the
        end of a victory, the next level of that trail opens and the points come (within the daily limit)."""
        with self.db.tx() as conn:
            row = conn.execute("SELECT state, actions, status, level, team FROM battles WHERE user = ? AND id = ?", (user, battle_id)).fetchone()
            if row is None:
                raise GameError("combat inconnu", 404)
            if row[2] != "running":
                raise GameError("ce combat est terminé")
            battle = combat.Battle.from_dict(json.loads(row[0]))
            mine = {f.id for f in battle.alive("player")}
            if not choices or set(choices) - mine:
                raise GameError("un coup pour chacun de tes familiers encore debout", 422)
            try:
                events = combat.play_round(self.cfg, self.bc, battle, choices)
            except combat.InvalidAction as e:
                raise GameError(str(e), 422) from e
            actions = json.loads(row[1]) + [{k: list(v) for k, v in choices.items()}]
            progress = "team_cleared" if row[4] else "cleared"
            reward = 0
            if battle.status != "running":
                level = row[3]
                if battle.status == "won":
                    cleared = conn.execute(f"SELECT {progress} FROM battle_progress WHERE user = ?", (user,)).fetchone()
                    cleared = cleared[0] if cleared else 0
                    first = level > cleared
                    today = now_iso()[:10]
                    done_today = conn.execute("SELECT count(*) FROM battles WHERE user = ? AND reward > 0 AND substr(finished_at, 1, 10) = ?",
                                              (user, today)).fetchone()[0]
                    if done_today < self.bc.p["daily_rewarded"]:
                        reward = combat.reward_for(self.bc, level, first)
                        self.wallet.apply(conn, user, {"key": f"battle:{battle_id}", "amount": reward, "kind": "battle", "date": now_iso(),
                                                       "label": f"Victoire au niveau {level}{' (équipe)' if row[4] else ''}",
                                                       "detail": {"level": level, "first": first, "team": bool(row[4])}})
                    if first:
                        conn.execute(f"INSERT INTO battle_progress (user, {progress}) VALUES (?, ?)"
                                     f" ON CONFLICT(user) DO UPDATE SET {progress} = excluded.{progress}", (user, level))
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
        again = combat.replay(self.cfg, self.bc, json.loads(initial), [a if isinstance(a, dict) else tuple(a) for a in json.loads(actions)])
        return again.to_dict() == json.loads(state)
