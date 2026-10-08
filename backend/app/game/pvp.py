"""Friendly battles, live, 1 against 1 or 3 against 3: I challenge a friend, they accept, then each round we both
choose a move for each of our fighters; the round is resolved (combat.play_round) once both have played, or
when the time is up (TURN_SECONDS): whoever did not play gets moves from the AI, and loses after MAX_MISSES
rounds missed in a row. No points, only a record. A chat, for the two players only.

The challenger plays the engine's "player" side (fighters "p" / "p1".."p3"), the friend its "enemy" side ("e1"..);
each sees the battle from their own side. "balanced": all familiers fight at the same stage and level.
Everything happens on requests (no background job): a late round is resolved by whoever asks next.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from . import combat
from .config import GameConfig
from .db import GameDB
from .battles import TEAM_SIZE, team_fighters
from .friends import Friends
from .pets import GameError, Pets, stats
from .wallet import now_iso

TURN_SECONDS = 30
INVITE_SECONDS = 300
MAX_MISSES = 2
BALANCED_STAGE = "adult"
BALANCED_LEVEL = 50
CHAT_MAX = 200  # characters per message
CHAT_EVERY = 1.0  # seconds between two messages of the same player
CHAT_KEEP = 100  # messages shown


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _later(seconds: int) -> str:
    return (_now() + timedelta(seconds=seconds)).isoformat()


class Pvp:
    def __init__(self, db: GameDB, pets: Pets, friends: Friends, cfg: GameConfig):
        self.db, self.pets, self.friends, self.cfg = db, pets, friends, cfg
        self.bc = combat.default(cfg)

    # --- invitations ---

    def _busy(self, conn, user: str) -> bool:
        return conn.execute("SELECT 1 FROM pvp WHERE (challenger = ? OR opponent = ?) AND status = 'running'", (user, user)).fetchone() is not None

    def challenge(self, user: str, friend: str, mode: str, team: bool = False, pets: list[int] | None = None) -> int:
        if mode not in ("normal", "balanced"):
            raise GameError("mode : normal ou balanced", 422)
        if not self.friends.are_friends(user, friend):
            raise GameError(f"{friend} n'est pas (encore) ton ami", 409)
        self._fighters(user, mode, team, pets, "player")  # familiers able to fight, before inviting
        with self.db.tx() as conn:
            self._expire(conn)
            if self._busy(conn, user):
                raise GameError("tu as déjà un combat amical en cours")
            if conn.execute("SELECT 1 FROM pvp WHERE challenger = ? AND opponent = ? AND status = 'invited'", (user, friend)).fetchone():
                raise GameError(f"défi déjà envoyé à {friend}")
            return conn.execute("INSERT INTO pvp (challenger, opponent, mode, status, seed, deadline, team, challenger_pets, created_at, updated_at)"
                                " VALUES (?,?,?,'invited',?,?,?,?,?,?)",
                                (user, friend, mode, secrets.token_hex(8), _later(INVITE_SECONDS), int(team),
                                 json.dumps(pets) if team else None, now_iso(), now_iso())).lastrowid

    def _fighters(self, user: str, mode: str, team: bool, pet_ids: list[int] | None, side: str) -> list[combat.Fighter]:
        balanced = (lambda sp: stats(self.cfg, sp, self.cfg.stage_index(BALANCED_STAGE), BALANCED_LEVEL)) if mode == "balanced" else None
        try:
            out = team_fighters(self.cfg, self.bc, self.pets, user, pet_ids, team, side, "p" if side == "player" else "e", balanced)
        except GameError as e:
            raise GameError(f"{user} : {e}", e.status) from e
        for f in out:
            f.name = f"{f.name} ({user})"
        return out

    def accept(self, user: str, pvp_id: int, pets: list[int] | None = None) -> None:
        """Take up a challenge (in 3 against 3, with the 3 familiers I choose)."""
        with self.db.tx() as conn:
            self._expire(conn)
            row = conn.execute("SELECT challenger, opponent, mode, status, seed, team, challenger_pets FROM pvp WHERE id = ?", (pvp_id,)).fetchone()
            if not row or row[1] != user or row[3] != "invited":
                raise GameError("défi introuvable ou expiré", 404)
            challenger, _, mode, _, seed, team, ch_pets = row
            if self._busy(conn, user) or self._busy(conn, challenger):
                raise GameError("l'un de vous est déjà dans un combat amical")
            fighters = self._fighters(challenger, mode, bool(team), json.loads(ch_pets) if ch_pets else None, "player")
            fighters += self._fighters(user, mode, bool(team), pets, "enemy")
            battle = combat.Battle(seed, 0, fighters)
            state = json.dumps(battle.to_dict(), ensure_ascii=False)
            conn.execute("UPDATE pvp SET status = 'running', initial = ?, state = ?, deadline = ?, misses = ?, opponent_pets = ?, updated_at = ?"
                         " WHERE id = ?", (state, state, _later(TURN_SECONDS), json.dumps({"player": 0, "enemy": 0}),
                                           json.dumps(pets) if team else None, now_iso(), pvp_id))

    def decline(self, user: str, pvp_id: int) -> None:
        """The friend says no (or the challenger takes the challenge back)."""
        with self.db.tx() as conn:
            row = conn.execute("SELECT challenger, opponent, status FROM pvp WHERE id = ?", (pvp_id,)).fetchone()
            if not row or user not in row[:2] or row[2] != "invited":
                raise GameError("défi introuvable", 404)
            conn.execute("UPDATE pvp SET status = ?, updated_at = ? WHERE id = ?",
                         ("cancelled" if user == row[0] else "declined", now_iso(), pvp_id))

    def _expire(self, conn) -> None:
        conn.execute("UPDATE pvp SET status = 'expired', updated_at = ? WHERE status = 'invited' AND deadline < ?", (now_iso(), now_iso()))

    def inbox(self, user: str) -> dict:
        now = now_iso()
        rows = self.db.read("SELECT id, challenger, opponent, mode, status, deadline, team FROM pvp WHERE (challenger = ? OR opponent = ?)"
                            " AND (status = 'running' OR (status = 'invited' AND deadline >= ?)) ORDER BY id DESC", (user, user, now))
        out = {"incoming": [], "outgoing": [], "running": None, "team_size": TEAM_SIZE}
        for pid, ch, op, mode, status, deadline, team in rows:
            if status == "running":
                out["running"] = out["running"] or pid
            else:
                (out["incoming"] if op == user else out["outgoing"]).append({"id": pid, "from": ch, "to": op, "mode": mode, "team": bool(team),
                                                                             "expires": deadline})
        return out

    def record(self, user: str, friend: str) -> dict:
        rows = self.db.read("SELECT winner FROM pvp WHERE status = 'done' AND ((challenger = ? AND opponent = ?) OR (challenger = ? AND opponent = ?))",
                            (user, friend, friend, user))
        return {"wins": sum(r[0] == user for r in rows), "losses": sum(r[0] == friend for r in rows), "draws": sum(r[0] is None for r in rows)}

    # --- the battle ---

    def _side(self, row, user: str) -> str:
        if user == row["challenger"]:
            return "player"
        if user == row["opponent"]:
            return "enemy"
        raise GameError("combat introuvable", 404)  # not one of theirs: as if it did not exist

    def _load(self, conn, pvp_id: int) -> dict:
        r = conn.execute("SELECT id, challenger, opponent, mode, status, state, actions, rounds, pending, misses, deadline, winner, end_reason"
                         " FROM pvp WHERE id = ?", (pvp_id,)).fetchone()
        if r is None:
            raise GameError("combat introuvable", 404)
        keys = ("id", "challenger", "opponent", "mode", "status", "state", "actions", "rounds", "pending", "misses", "deadline", "winner", "end_reason")
        row = dict(zip(keys, r))
        for k in ("actions", "rounds", "pending", "misses"):
            row[k] = json.loads(row[k] or "{}")
        return row

    def move(self, user: str, pvp_id: int, choices: dict[str, tuple[str, str | None]]) -> dict:
        """My moves for this round: one (and a target) for each of my fighters still standing."""
        with self.db.tx() as conn:
            row = self._load(conn, pvp_id)
            side = self._side(row, user)
            if row["status"] != "running":
                raise GameError("ce combat est terminé")
            self._resolve_if_late(conn, row)
            if row["status"] == "running":
                battle = combat.Battle.from_dict(json.loads(row["state"]))
                mine = {f.id for f in battle.alive(side)}
                if set(choices) != mine:
                    raise GameError("un coup pour chacun de tes familiers encore debout", 422)
                try:
                    for fid, (mv, _) in choices.items():
                        combat.check_choice(self.cfg, self.bc, battle, fid, mv)
                except combat.InvalidAction as e:
                    raise GameError(str(e), 422) from e
                row["pending"][side] = {fid: list(c) for fid, c in choices.items()}
                row["misses"][side] = 0
                if len(row["pending"]) == 2:
                    self._resolve(conn, row)
                else:
                    self._save(conn, row)
        return self.view(user, pvp_id)

    def forfeit(self, user: str, pvp_id: int) -> None:
        with self.db.tx() as conn:
            row = self._load(conn, pvp_id)
            side = self._side(row, user)
            if row["status"] == "running":
                self._finish(conn, row, winner=row["opponent"] if side == "player" else row["challenger"], reason="abandon")

    def _resolve_if_late(self, conn, row: dict) -> None:
        if row["status"] == "running" and row["deadline"] and row["deadline"] < now_iso():
            self._resolve(conn, row)

    def _resolve(self, conn, row: dict) -> None:
        """Play the round: the moves chosen, the AI for whoever did not play (who loses after MAX_MISSES)."""
        battle = combat.Battle.from_dict(json.loads(row["state"]))
        choices = {}
        for side in ("player", "enemy"):
            if side in row["pending"]:
                choices.update({fid: tuple(c) for fid, c in row["pending"][side].items()})
            else:
                row["misses"][side] = row["misses"].get(side, 0) + 1
                if row["misses"][side] >= MAX_MISSES:
                    loser = row["challenger"] if side == "player" else row["opponent"]
                    return self._finish(conn, row, winner=row["opponent"] if side == "player" else row["challenger"],
                                        reason=f"{loser} n'a pas joué à temps")
                for f in battle.alive(side):
                    choices[f.id] = (combat.ai_choice(self.cfg, self.bc, battle, f.id), None)
        events = combat.play_round(self.cfg, self.bc, battle, choices)
        row["actions"].append({k: list(v) for k, v in choices.items()})
        row["rounds"].append({"turn": len(row["rounds"]) + 1, "events": events})
        row["pending"] = {}
        row["state"] = json.dumps(battle.to_dict(), ensure_ascii=False)
        row["deadline"] = _later(TURN_SECONDS)
        if battle.status != "running":
            if battle.end_reason == "à bout de souffle":  # time's up: the side with the most HP left
                share = lambda side: sum(f.hp for f in battle.side_of(side)) / sum(f.max_hp for f in battle.side_of(side))  # noqa: E731
                rp, re_ = share("player"), share("enemy")
                winner = row["challenger"] if rp > re_ else row["opponent"] if re_ > rp else None
            else:
                winner = row["challenger"] if battle.status == "won" else row["opponent"]
            return self._finish(conn, row, winner, battle.end_reason or "K.O.")
        self._save(conn, row)

    def _finish(self, conn, row: dict, winner: str | None, reason: str) -> None:
        row["status"], row["winner"], row["end_reason"] = "done", winner, reason
        self._save(conn, row)

    def _save(self, conn, row: dict) -> None:
        conn.execute("UPDATE pvp SET status = ?, state = ?, actions = ?, rounds = ?, pending = ?, misses = ?, deadline = ?, winner = ?,"
                     " end_reason = ?, updated_at = ? WHERE id = ?",
                     (row["status"], row["state"], json.dumps(row["actions"]), json.dumps(row["rounds"], ensure_ascii=False),
                      json.dumps(row["pending"]), json.dumps(row["misses"]), row["deadline"], row["winner"], row["end_reason"],
                      now_iso(), row["id"]))

    def view(self, user: str, pvp_id: int, since: int = 0) -> dict:
        """The battle from `user`'s side: fighters (mine with my moves), the rounds after `since` to animate, whether
        each of us has played this round, the seconds left, and the result."""
        with self.db.tx() as conn:  # a late round is resolved by whoever asks
            row = self._load(conn, pvp_id)
            side = self._side(row, user)
            self._resolve_if_late(conn, row)
        friend = row["opponent"] if side == "player" else row["challenger"]
        team = self.db.read("SELECT team FROM pvp WHERE id = ?", (pvp_id,))[0][0]
        out = {"id": row["id"], "pvp": True, "mode": row["mode"], "team": bool(team), "status": row["status"], "friend": friend,
               "rounds": [r for r in row["rounds"] if r["turn"] > since], "round": len(row["rounds"]), "chat": self.chat(user, pvp_id)}
        if row["state"]:
            battle = combat.Battle.from_dict(json.loads(row["state"]))
            out.update(combat.battle_view(self.cfg, self.bc, battle, mine=side))
            out["status"] = row["status"]  # the pvp status (invited, running, done…), not the engine's won / lost
        out["played"] = side in row["pending"]
        out["friend_played"] = ("enemy" if side == "player" else "player") in row["pending"]
        if row["status"] == "running" and row["deadline"]:
            out["seconds_left"] = max(0, int((datetime.fromisoformat(row["deadline"]) - _now()).total_seconds()))
        if row["status"] == "done":
            out["result"] = "draw" if row["winner"] is None else "won" if row["winner"] == user else "lost"
            out["end_reason"] = row["end_reason"]
        return out

    # --- the chat of the battle (the two players only) ---

    def _player_of(self, user: str, pvp_id: int) -> None:
        rows = self.db.read("SELECT challenger, opponent FROM pvp WHERE id = ?", (pvp_id,))
        if not rows or user not in rows[0]:
            raise GameError("combat introuvable", 404)

    def say(self, user: str, pvp_id: int, text: str) -> None:
        self._player_of(user, pvp_id)
        text = " ".join(text.split())[:CHAT_MAX]
        if not text:
            raise GameError("message vide", 422)
        with self.db.tx() as conn:
            last = conn.execute("SELECT created_at FROM pvp_chat WHERE pvp_id = ? AND user = ? ORDER BY id DESC LIMIT 1", (pvp_id, user)).fetchone()
            if last and (_now() - datetime.fromisoformat(last[0])).total_seconds() < CHAT_EVERY:
                raise GameError("doucement : un message par seconde", 429)
            conn.execute("INSERT INTO pvp_chat (pvp_id, user, text, created_at) VALUES (?,?,?,?)", (pvp_id, user, text, now_iso()))

    def chat(self, user: str, pvp_id: int) -> list[dict]:
        self._player_of(user, pvp_id)
        rows = self.db.read("SELECT id, user, text, created_at FROM pvp_chat WHERE pvp_id = ? ORDER BY id DESC LIMIT ?", (pvp_id, CHAT_KEEP))
        return [{"id": i, "from": u, "mine": u == user, "text": t, "at": at} for i, u, t, at in reversed(rows)]

    def check_replay(self, pvp_id: int) -> bool:
        rows = self.db.read("SELECT initial, actions, state FROM pvp WHERE id = ?", (pvp_id,))
        initial, actions, state = rows[0]
        return combat.replay(self.cfg, self.bc, json.loads(initial), json.loads(actions)).to_dict() == json.loads(state)
