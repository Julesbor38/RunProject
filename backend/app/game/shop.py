"""The shop: familiers (and later objects) paid in points or in gems, and gem packs paid with real money.

Every purchase is deterministic (the item says exactly what it gives) and runs in one transaction: the price
is taken (wallet.apply: refused if the balance does not cover it), the familier is created, the purchase is
recorded. The same request_id again returns the first purchase, without paying twice.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import GameConfig
from .db import GameDB
from .payments import PaymentProvider
from .pets import GameError, Pets
from .wallet import Wallet, now_iso


@dataclass
class Purchase:
    id: int
    item: str
    currency: str
    price: float
    pet_id: int | None
    replayed: bool = False


class Shop:
    def __init__(self, db: GameDB, wallet: Wallet, pets: Pets, cfg: GameConfig, payments: PaymentProvider):
        self.db, self.wallet, self.pets, self.cfg, self.payments = db, wallet, pets, cfg, payments

    def owned_species(self, user: str) -> set[str]:
        return {r[0] for r in self.db.read("SELECT species FROM pets WHERE user = ? AND origin = 'shop'", (user,))}

    def buy(self, user: str, item_id: str, currency: str, request_id: str) -> Purchase:
        item = self.cfg.shop.get(item_id)
        if item is None:
            raise GameError("article inconnu", 404)
        price = {"points": item.price_points, "gems": item.price_gems}.get(currency)
        if price is None:
            raise GameError(f"cet article ne se paie pas en {'points' if currency == 'points' else 'gemmes'}", 422)
        if item.random and currency != "points":  # also refused by the config check: never gems for a draw
            raise GameError("un tirage aléatoire ne se paie qu'en points", 422)
        with self.db.tx() as conn:
            done = conn.execute("SELECT id, item, currency, price, pet_id FROM purchases WHERE user = ? AND request_id = ?",
                                (user, request_id)).fetchone()
            if done:
                return Purchase(*done, replayed=True)
            sp = self.cfg.species[item.species]
            if conn.execute("SELECT 1 FROM pets WHERE user = ? AND origin = 'shop' AND species = ?", (user, sp.id)).fetchone():
                raise GameError(f"{sp.names[1]} est déjà dans ta collection")
            self.wallet.apply(conn, user, {"key": f"shop:{request_id}", "amount": -price, "kind": "shop", "date": now_iso(),
                                           "label": f"Boutique : {sp.names[0]}", "detail": {"item": item.id}}, currency)
            conn.execute("UPDATE pets SET active = 0 WHERE user = ?", (user,))
            pet_id = conn.execute(
                "INSERT INTO pets (user, species, name, origin, active, acquired_at, profile_since) VALUES (?, ?, ?, 'shop', 1, ?, ?)",
                (user, sp.id, sp.names[1], now_iso(), now_iso()),  # its running profile starts now
            ).lastrowid
            pid = conn.execute("INSERT INTO purchases (user, item, currency, price, request_id, pet_id, created_at) VALUES (?,?,?,?,?,?,?)",
                               (user, item.id, currency, price, request_id, pet_id, now_iso())).lastrowid
        return Purchase(pid, item.id, currency, price, pet_id)

    def buy_gems(self, user: str, pack_id: str, request_id: str, receipt: str | None = None) -> Purchase:
        """A gem pack: the provider confirms the payment, then the gems are credited (once per payment)."""
        pack = self.cfg.gem_packs.get(pack_id)
        if pack is None:
            raise GameError("pack inconnu", 404)
        done = self.db.read("SELECT id, item, currency, price, pet_id FROM purchases WHERE user = ? AND request_id = ?", (user, request_id))
        if done:
            return Purchase(*done[0], replayed=True)
        payment = self.payments.confirm(user, pack, request_id, receipt)
        with self.db.tx() as conn:
            if conn.execute("SELECT 1 FROM purchases WHERE provider = ? AND receipt = ?", (payment.provider, payment.receipt)).fetchone():
                raise GameError("ce paiement a déjà été crédité")
            self.wallet.apply(conn, user, {"key": f"gems:{request_id}", "amount": pack.gems, "kind": "purchase", "date": now_iso(),
                                           "label": f"Achat de {pack.gems} gemmes", "detail": {"pack": pack.id, "provider": payment.provider}}, "gems")
            pid = conn.execute(
                "INSERT INTO purchases (user, item, currency, price, request_id, provider, receipt, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (user, pack.id, "eur", pack.price_eur, request_id, payment.provider, payment.receipt, now_iso())).lastrowid
        return Purchase(pid, pack.id, "eur", pack.price_eur, None)
