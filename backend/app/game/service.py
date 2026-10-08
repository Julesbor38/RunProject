"""The game of one data root: its database, wallet, familiers and configuration, and what the API shows."""
from __future__ import annotations

from pathlib import Path

from . import config
from .db import GameDB
from .payments import PaymentProvider, provider_from_env
from .pets import Pet, Pets, branch_scores, profile_metrics, stats
from .shop import Shop
from .wallet import Wallet


class Game:
    def __init__(self, path: Path, cfg: config.GameConfig | None = None, payments: PaymentProvider | None = None):
        self.cfg = cfg or config.default()
        self.db = GameDB(path)
        self.wallet = Wallet(self.db)
        self.pets = Pets(self.db, self.wallet, self.cfg)
        self.shop = Shop(self.db, self.wallet, self.pets, self.cfg, payments or provider_from_env())

    def abilities_json(self, sp: config.Species, stage: int | None = None, branch: str | None = None) -> list[dict]:
        """The species' abilities (those of its branch for the final form), and whether they are unlocked."""
        out = []
        for a in sp.abilities:
            if a.branch and branch and a.branch != branch:
                continue
            at = self.cfg.stage_index(a.stage)
            out.append({"id": a.id, "name": a.name, "kind": a.kind, "power": a.power, "value": a.value, "description": a.description,
                        "stage": self.cfg.stages[at].name, "branch": a.branch, "unlocked": stage is not None and stage >= at})
        return out

    def species_json(self, sp: config.Species) -> dict:
        return {"id": sp.id, "type": sp.type, "type_name": self.cfg.types[sp.type], "names": list(sp.names),
                "color": sp.color, "description": sp.description, "base": sp.base, "total": sum(sp.base.values()),
                "rarity": sp.rarity, "rarity_name": config.RARITIES.get(sp.rarity or ""),
                "branches": [{"id": b.id, "name": b.name, "type": b.type, "hint": b.hint} for b in sp.branches],
                "abilities": self.abilities_json(sp),
                "final_stats": stats(self.cfg, sp, self.cfg.final, self.cfg.stages[-1].max_level)}

    def shop_json(self, user: str) -> dict:
        owned = self.shop.owned_species(user)
        items = []
        for item in self.cfg.shop.values():
            sp = self.cfg.species[item.species]
            items.append({"id": item.id, "kind": item.kind, "price_points": item.price_points, "price_gems": item.price_gems,
                          "random": item.random, "owned": sp.id in owned, "species": self.species_json(sp)})
        return {"items": items, "wallet": self.wallet.balances(user), "payments": self.shop.payments.name,
                "gem_packs": [{"id": p.id, "gems": p.gems, "price_eur": p.price_eur, "label": p.label} for p in self.cfg.gem_packs.values()],
                "starter_total": max((sum(s.base.values()) for s in self.cfg.starters()), default=0)}

    def pet_json(self, pet: Pet, balance: int, activities: list[dict] | None = None) -> dict:
        """Everything the familier's screen shows: form, stage, level, stats, what the next level and the
        evolution cost, and (from the adult stage) which branch the running profile leans towards."""
        cfg, sp = self.cfg, self.pets.species_of(pet)
        stage = cfg.stages[pet.stage]
        at_cap = pet.level >= stage.max_level
        nxt = cfg.stages[pet.stage + 1] if pet.stage < cfg.final else None
        affordable = 0 if at_cap else self.pets.levels_affordable(pet, balance)
        out = {
            "id": pet.id, "name": pet.name, "species": sp.id, "form": self.pets.form_name(pet), "type": self.pets.type_of(pet),
            "type_name": cfg.types[self.pets.type_of(pet)], "color": sp.color, "active": pet.active, "origin": pet.origin,
            "stage": {"index": pet.stage, "id": stage.id, "name": stage.name, "max_level": stage.max_level, "final": pet.stage == cfg.final},
            "level": pet.level, "branch": pet.branch, "stats": self.pets.stats(pet),
            "rarity": sp.rarity, "rarity_name": config.RARITIES.get(sp.rarity or ""),
            "abilities": self.abilities_json(sp, pet.stage, pet.branch),
            "next_level": None if at_cap else {
                "cost": cfg.level_cost(pet.level + 1),
                "cost_5": cfg.levels_cost(pet.level, min(stage.max_level, pet.level + 5)),
                "levels_5": min(5, stage.max_level - pet.level),
                "affordable": affordable,  # « Max » : what the points buy now, and its cost
                "affordable_cost": cfg.levels_cost(pet.level, pet.level + affordable),
            },
            "evolution": None if not nxt else {
                "stage": nxt.name, "level": stage.max_level, "ready": at_cap, "cost": nxt.evolve_cost,
                "stats": stats(cfg, sp, nxt.index, pet.level),
                "form": sp.names[nxt.index] if nxt.index < len(sp.names) else None,
            },
        }
        if nxt is not None and nxt.index == cfg.final and activities is not None:
            metrics = profile_metrics(activities)
            scores = dict(branch_scores(sp, metrics))
            lead = max(sp.branches, key=lambda b: (scores[b.id], -sp.branches.index(b)))
            out["evolution"]["branches"] = [{"id": b.id, "name": b.name, "type": b.type, "type_name": cfg.types[b.type], "hint": b.hint,
                                             "score": round(scores[b.id], 2), "leading": b is lead} for b in sp.branches]
            out["evolution"]["profile"] = {k: round(v, 3) for k, v in metrics.items()}
        return out
