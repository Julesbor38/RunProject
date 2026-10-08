"""The game's SQLite database (data/game/game.sqlite): numbered migrations (migrations/NNN_*.sql, applied in
order at start-up, tracked by PRAGMA user_version) and serialized write transactions."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"


class GameDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        # isolation_level=None: transactions are explicit (BEGIN IMMEDIATE below), never implicit.
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=15)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> int:
        """Apply the migrations not applied yet. Returns the schema version."""
        with self.lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for file in sorted(MIGRATIONS.glob("*.sql")):
                n = int(file.name.split("_", 1)[0])
                if n <= version:
                    continue
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _statements(file.read_text()):
                        self.conn.execute(statement)
                    self.conn.execute(f"PRAGMA user_version = {n}")
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
                version = n
            return version

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction: BEGIN IMMEDIATE takes the database's write lock first, so two transactions
        (threads, or processes on the same file) never read the same balance before writing it."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def read(self, sql: str, args: tuple | list = ()) -> list[tuple]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()


def _statements(script: str) -> list[str]:
    """The statements of a migration file, without their comments (our migrations have no ';' nor '--' in strings)."""
    lines = [l.split("--", 1)[0] for l in script.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
