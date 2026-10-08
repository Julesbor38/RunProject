"""Friends: a request by user name, accepted or declined; removing a friend; blocking someone (they can no longer
ask). Friends see each other's user name, familiers and record of friendly battles, nothing else: never the
activities, tracks, towns or balances of the other (where someone runs stays private)."""
from __future__ import annotations

from collections.abc import Callable

from .db import GameDB
from .pets import GameError
from .wallet import now_iso


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


class Friends:
    def __init__(self, db: GameDB, exists: Callable[[str], bool]):
        self.db, self.exists = db, exists

    def _row(self, conn, a: str, b: str):
        return conn.execute("SELECT status, requested_by, blocked_by FROM friendships WHERE user_a = ? AND user_b = ?", _pair(a, b)).fetchone()

    def request(self, user: str, other: str) -> str:
        """Ask `other` to be friends (or accept, if they already asked). Returns the new status."""
        other = other.strip().lower()
        if other == user:
            raise GameError("tu ne peux pas t'ajouter toi-même", 422)
        if not self.exists(other):
            raise GameError("aucun compte à ce nom", 404)
        a, b = _pair(user, other)
        with self.db.tx() as conn:
            row = self._row(conn, user, other)
            if row and row[0] == "blocked":
                raise GameError("demande impossible", 409)  # never tells who blocked whom
            if row and row[0] == "accepted":
                raise GameError(f"{other} est déjà ton ami")
            if row and row[0] == "pending":
                if row[1] == user:
                    raise GameError("demande déjà envoyée")
                conn.execute("UPDATE friendships SET status = 'accepted', updated_at = ? WHERE user_a = ? AND user_b = ?", (now_iso(), a, b))
                return "accepted"
            conn.execute("INSERT INTO friendships (user_a, user_b, status, requested_by, created_at, updated_at) VALUES (?,?,'pending',?,?,?)",
                         (a, b, user, now_iso(), now_iso()))
        return "pending"

    def respond(self, user: str, other: str, accept: bool) -> None:
        a, b = _pair(user, other)
        with self.db.tx() as conn:
            row = self._row(conn, user, other)
            if not row or row[0] != "pending" or row[1] == user:
                raise GameError("aucune demande de ce compte", 404)
            if accept:
                conn.execute("UPDATE friendships SET status = 'accepted', updated_at = ? WHERE user_a = ? AND user_b = ?", (now_iso(), a, b))
            else:
                conn.execute("DELETE FROM friendships WHERE user_a = ? AND user_b = ?", (a, b))

    def remove(self, user: str, other: str) -> None:
        """Remove a friend, or cancel a request (sent or received)."""
        with self.db.tx() as conn:
            row = self._row(conn, user, other)
            if row and row[0] != "blocked":
                conn.execute("DELETE FROM friendships WHERE user_a = ? AND user_b = ?", _pair(user, other))

    def block(self, user: str, other: str) -> None:
        other = other.strip().lower()
        if other == user or not self.exists(other):
            raise GameError("aucun compte à ce nom", 404)
        a, b = _pair(user, other)
        with self.db.tx() as conn:
            conn.execute("INSERT INTO friendships (user_a, user_b, status, blocked_by, created_at, updated_at) VALUES (?,?,'blocked',?,?,?)"
                         " ON CONFLICT(user_a, user_b) DO UPDATE SET status = 'blocked', blocked_by = excluded.blocked_by, requested_by = NULL,"
                         " updated_at = excluded.updated_at", (a, b, user, now_iso(), now_iso()))

    def unblock(self, user: str, other: str) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM friendships WHERE user_a = ? AND user_b = ? AND status = 'blocked' AND blocked_by = ?", (*_pair(user, other), user))

    def are_friends(self, a: str, b: str) -> bool:
        rows = self.db.read("SELECT status FROM friendships WHERE user_a = ? AND user_b = ?", _pair(a, b))
        return bool(rows) and rows[0][0] == "accepted"

    def lists(self, user: str) -> dict:
        rows = self.db.read("SELECT user_a, user_b, status, requested_by, blocked_by FROM friendships WHERE user_a = ? OR user_b = ?", (user, user))
        out = {"friends": [], "incoming": [], "outgoing": [], "blocked": []}
        for a, b, status, req, blk in rows:
            other = b if a == user else a
            if status == "accepted":
                out["friends"].append(other)
            elif status == "pending":
                out["outgoing" if req == user else "incoming"].append(other)
            elif blk == user:
                out["blocked"].append(other)
        return {k: sorted(v) for k, v in out.items()}
