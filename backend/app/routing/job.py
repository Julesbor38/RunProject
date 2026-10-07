"""Progress and cancellation of one route generation, shared with the API thread that polls it."""
from __future__ import annotations

import threading


class Cancelled(Exception):
    pass


class Job:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self.stage = "start"  # "download" (OSM tiles), "graph", "routes"
        self.done = 0
        self.total = 0

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        """Raise Cancelled when the user gave up; called between steps of the work."""
        if self._cancel.is_set():
            raise Cancelled

    def step(self, stage: str, done: int = 0, total: int = 0) -> None:
        self.check()
        self.stage, self.done, self.total = stage, done, total

    def advance(self) -> None:
        self.check()
        self.done += 1

    def progress(self) -> dict:
        return {"stage": self.stage, "done": self.done, "total": self.total, "cancelled": self.cancelled}
