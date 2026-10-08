"""Payments with real money, for gem packs only (points are never bought). A provider confirms a payment and
the gems are credited once per payment (the request id, then the provider's receipt, are unique).

Only a mock exists yet (TRAILMAP_PAYMENTS=mock): it accepts every purchase without charging anything, for
development. Later: App Store in-app purchases in the iOS app (Apple requires them for a virtual currency),
Stripe on the web; each implements `PaymentProvider.confirm` by checking the receipt with its service.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .config import GemPack


class PaymentError(Exception):
    def __init__(self, message: str, status: int = 402):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Payment:
    provider: str
    receipt: str  # the provider's proof, kept with the purchase


class PaymentProvider(Protocol):
    name: str

    def confirm(self, user: str, pack: GemPack, request_id: str, receipt: str | None) -> Payment:
        """Check that `pack` was paid (raise PaymentError otherwise) and return the proof."""


class DisabledPayments:
    name = "disabled"

    def confirm(self, user, pack, request_id, receipt):
        raise PaymentError("l'achat de gemmes n'est pas encore disponible", 503)


class MockPayments:
    """Development only: every purchase is accepted, nothing is charged."""

    name = "mock"

    def confirm(self, user, pack, request_id, receipt):
        return Payment("mock", f"mock:{user}:{pack.id}:{request_id}")


def provider_from_env() -> PaymentProvider:
    return MockPayments() if os.environ.get("TRAILMAP_PAYMENTS") == "mock" else DisabledPayments()
