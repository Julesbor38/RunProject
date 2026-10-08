"""Wallet of each account: points (earned by running, exploring, rating; never bought) and gems (bought later,
see the shop step), with their ledger (`transactions`).

The balance is a column updated in the same transaction as the ledger row that changes it, and a spending
only goes through if the balance covers it (`UPDATE … WHERE points >= amount`, under the database's write
lock): no double spending, even with two requests at the same time. Every row has a key, unique per
account and currency, so a gain or a retried purchase never counts twice.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .db import GameDB

CURRENCIES = ("points", "gems")


class InsufficientFunds(Exception):
    def __init__(self, currency: str, needed: int, balance: int):
        self.currency, self.needed, self.balance = currency, needed, balance
        name = "points" if currency == "points" else "gemmes"
        super().__init__(f"{name} insuffisants : {needed} nécessaires, solde de {balance}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Wallet:
    def __init__(self, db: GameDB):
        self.db = db

    # --- inside a transaction (db.tx()): what a purchase combines with its own changes ---

    @staticmethod
    def balance_in(conn: sqlite3.Connection, user: str, currency: str = "points") -> int:
        row = conn.execute(f"SELECT {_col(currency)} FROM wallets WHERE user = ?", (user,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def has_key(conn: sqlite3.Connection, user: str, key: str, currency: str = "points") -> bool:
        return conn.execute("SELECT 1 FROM transactions WHERE user = ? AND currency = ? AND key = ?", (user, currency, key)).fetchone() is not None

    def apply(self, conn: sqlite3.Connection, user: str, entry: dict, currency: str = "points") -> int | None:
        """Record one ledger row and move the balance (unless it is history). Returns the new balance, or None
        if that key was already recorded. Raises InsufficientFunds if a spending is not covered."""
        col = _col(currency)
        if self.has_key(conn, user, entry["key"], currency):
            return None
        conn.execute("INSERT OR IGNORE INTO wallets (user) VALUES (?)", (user,))
        amount = int(entry["amount"])
        history = bool(entry.get("history", False))
        if not history and amount:
            cur = conn.execute(f"UPDATE wallets SET {col} = {col} + ? WHERE user = ? AND {col} + ? >= 0", (amount, user, amount))
            if cur.rowcount == 0:
                raise InsufficientFunds(currency, -amount, self.balance_in(conn, user, currency))
        balance = self.balance_in(conn, user, currency)
        conn.execute(
            "INSERT INTO transactions (user, currency, amount, kind, key, label, date, detail, history, balance_after, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user, currency, amount, entry["kind"], entry["key"], entry.get("label", ""), entry.get("date"),
             json.dumps(entry.get("detail") or {}, ensure_ascii=False), int(history), None if history else balance, now_iso()),
        )
        return balance

    # --- one transaction each ---

    def credit(self, user: str, entries: list[dict], currency: str = "points") -> int:
        """Gains (and history rows), each once. Returns the rows added."""
        n = 0
        with self.db.tx() as conn:
            for e in entries:
                n += self.apply(conn, user, e, currency) is not None
        return n

    def debit(self, user: str, amount: int, kind: str, key: str, label: str, detail: dict | None = None,
              currency: str = "points", up_to: bool = False) -> int:
        """Take `amount` (all of it, or InsufficientFunds; `up_to`: as much as the balance allows). Returns what was
        taken (0 if that key was already recorded)."""
        with self.db.tx() as conn:
            if up_to:
                amount = min(amount, self.balance_in(conn, user, currency))
            if amount <= 0:
                return 0
            done = self.apply(conn, user, {"key": key, "amount": -amount, "kind": kind, "label": label,
                                           "date": now_iso(), "detail": detail}, currency)
        return amount if done is not None else 0

    # --- reading ---

    def balance(self, user: str, currency: str = "points") -> int:
        rows = self.db.read(f"SELECT {_col(currency)} FROM wallets WHERE user = ?", (user,))
        return rows[0][0] if rows else 0

    def balances(self, user: str) -> dict:
        rows = self.db.read("SELECT points, gems FROM wallets WHERE user = ?", (user,))
        return {"points": rows[0][0], "gems": rows[0][1]} if rows else {"points": 0, "gems": 0}

    def keys(self, user: str, currency: str = "points") -> set[str]:
        return {r[0] for r in self.db.read("SELECT key FROM transactions WHERE user = ? AND currency = ?", (user, currency))}

    def rows(self, user: str, currency: str = "points", history: bool | None = None, limit: int | None = None) -> list[dict]:
        """Ledger rows, newest first."""
        where, args = "user = ? AND currency = ?", [user, currency]
        if history is not None:
            where += " AND history = ?"
            args.append(int(history))
        sql = f"SELECT id, key, amount, kind, label, date, detail, history, balance_after, created_at FROM transactions WHERE {where} ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [{"id": r[0], "key": r[1], "amount": r[2], "kind": r[3], "label": r[4], "date": r[5], "detail": json.loads(r[6]),
                 "history": bool(r[7]), "balance_after": r[8], "created_at": r[9]} for r in self.db.read(sql, args)]

    # --- when the account's points began, last gain announced ---

    def start(self, user: str) -> tuple[str | None, int]:
        rows = self.db.read("SELECT points_start, seen FROM accounts WHERE user = ?", (user,))
        return (rows[0][0], rows[0][1]) if rows else (None, 0)

    def set_start(self, user: str, start: str) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO accounts (user, points_start) VALUES (?, ?)", (user, start))

    def mark_seen(self, user: str) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE accounts SET seen = (SELECT coalesce(max(id), 0) FROM transactions WHERE user = ?) WHERE user = ?", (user, user))

    def meta(self, key: str) -> str | None:
        rows = self.db.read("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0][0] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


def _col(currency: str) -> str:
    if currency not in CURRENCIES:
        raise ValueError(currency)
    return currency
