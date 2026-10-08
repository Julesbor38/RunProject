"""Game configuration: the TOML files of config/ (stages and level costs, types, species and their abilities,
shop), loaded and checked once. Editing a file and restarting the API is enough (see README.md)."""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"
STATS = ("hp", "attack", "defense", "speed")
METRICS = ("ascent_per_km", "night_share", "long_share", "fast_share", "new_share")
ABILITY_KINDS = ("strike", "guard", "heal", "haste", "drain")
RARITIES = {"rare": "Rare", "epique": "Épique", "legendaire": "Légendaire"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    index: int
    id: str
    name: str
    max_level: int
    evolve_cost: int
    stat_multiplier: float


@dataclass(frozen=True)
class Branch:
    id: str
    name: str
    type: str
    metric: str
    reference: float
    hint: str = ""
    type2: str | None = None  # a second type


@dataclass(frozen=True)
class Ability:
    id: str
    name: str
    kind: str
    stage: str  # unlocked at this stage
    power: int = 0
    value: int = 0
    branch: str | None = None  # final form only, with this branch
    description: str = ""


@dataclass(frozen=True)
class ShopItem:
    id: str
    kind: str  # "pet"
    species: str | None
    price_points: int | None
    price_gems: int | None
    random: bool = False


@dataclass(frozen=True)
class GemPack:
    id: str
    gems: int
    price_eur: float
    label: str = ""


@dataclass(frozen=True)
class Species:
    id: str
    type: str
    names: tuple[str, ...]  # one per stage before the final form
    base: dict[str, int]
    branches: tuple[Branch, ...]
    starter: bool = False
    color: str = "#888888"
    description: str = ""
    rarity: str | None = None
    abilities: tuple[Ability, ...] = ()
    type2: str | None = None  # a second type (both apply in battle: its kit, and the damage it takes)

    def branch(self, branch_id: str | None) -> Branch | None:
        return next((b for b in self.branches if b.id == branch_id), None)


@dataclass(frozen=True)
class GameConfig:
    stages: tuple[Stage, ...]
    cost_base: float
    cost_exponent: float
    stat_bonus_per_level: float
    types: dict[str, str]  # id -> name
    strong: dict[str, frozenset[str]]
    strong_multiplier: float
    weak_multiplier: float
    species: dict[str, Species] = field(default_factory=dict)
    shop: dict[str, ShopItem] = field(default_factory=dict)
    gem_packs: dict[str, GemPack] = field(default_factory=dict)

    def stage_index(self, stage_id: str) -> int:
        return next(s.index for s in self.stages if s.id == stage_id)

    @property
    def final(self) -> int:
        return len(self.stages) - 1

    def level_cost(self, level: int) -> int:
        """Points to reach `level` from the one below."""
        return math.ceil(self.cost_base * level**self.cost_exponent)

    def levels_cost(self, current: int, target: int) -> int:
        return sum(self.level_cost(n) for n in range(current + 1, target + 1))

    def effectiveness(self, attacker: str, defender: str, defender2: str | None = None) -> float:
        """A move of type `attacker` against a familier of type `defender` (and `defender2`: both multipliers)."""
        out = 1.0
        for d in (defender, defender2):
            if d is None:
                continue
            if d in self.strong.get(attacker, ()):
                out *= self.strong_multiplier
            elif attacker in self.strong.get(d, ()):
                out *= self.weak_multiplier
        return out

    def starters(self) -> list[Species]:
        return [s for s in self.species.values() if s.starter]


def _read(name: str, folder: Path) -> dict:
    with open(folder / name, "rb") as f:
        return tomllib.load(f)


def load(folder: Path = CONFIG_DIR) -> GameConfig:
    st, ty, sp = _read("stages.toml", folder), _read("types.toml", folder), _read("species.toml", folder)
    sh = _read("shop.toml", folder) if (folder / "shop.toml").exists() else {}
    stages = tuple(Stage(i, s["id"], s["name"], int(s["max_level"]), int(s["evolve_cost"]), float(s["stat_multiplier"]))
                   for i, s in enumerate(st["stage"]))
    types = dict(ty["names"])
    strong = {t: frozenset(ty["strong"].get(t, ())) for t in types}
    species = {}
    for s in sp["species"]:
        branches = tuple(Branch(b["id"], b["name"], b["type"], b["metric"], float(b["reference"]), b.get("hint", ""), b.get("type2"))
                         for b in s["branch"])
        abilities = tuple(Ability(a["id"], a["name"], a["kind"], a["stage"], int(a.get("power", 0)), int(a.get("value", 0)),
                                  a.get("branch"), a.get("description", "")) for a in s.get("ability", ()))
        species[s["id"]] = Species(s["id"], s["type"], tuple(s["names"]), {k: int(s["base"][k]) for k in STATS}, branches,
                                   bool(s.get("starter", False)), s.get("color", "#888888"), s.get("description", ""),
                                   s.get("rarity"), abilities, s.get("type2"))
    shop = {i["id"]: ShopItem(i["id"], i["kind"], i.get("species"), i.get("price_points"), i.get("price_gems"), bool(i.get("random", False)))
            for i in sh.get("item", ())}
    packs = {p["id"]: GemPack(p["id"], int(p["gems"]), float(p["price_eur"]), p.get("label", "")) for p in sh.get("gem_pack", ())}
    cfg = GameConfig(stages, float(st["levels"]["cost_base"]), float(st["levels"]["cost_exponent"]),
                     float(st["levels"]["stat_bonus_per_level"]), types, strong,
                     float(ty["strong_multiplier"]), float(ty["weak_multiplier"]), species, shop, packs)
    validate(cfg)
    return cfg


def validate(cfg: GameConfig) -> None:
    levels = [s.max_level for s in cfg.stages]
    if len(cfg.stages) < 2 or levels != sorted(set(levels)):
        raise ConfigError("stages: at least two, with growing max_level")
    for t, beaten in cfg.strong.items():
        if unknown := beaten - cfg.types.keys():
            raise ConfigError(f"types: {t} strong against unknown {sorted(unknown)}")
        if t in beaten:
            raise ConfigError(f"types: {t} strong against itself")
        if any(t in cfg.strong[o] for o in beaten):
            raise ConfigError(f"types: {t} and a type it beats are strong against each other")
    for t in cfg.types:
        weak = [o for o in cfg.types if t in cfg.strong[o]]
        if not cfg.strong[t] or not weak:
            raise ConfigError(f"types: {t} needs at least one strength and one weakness")
        if len(cfg.strong[t]) != len(weak):
            raise ConfigError(f"types: {t} has {len(cfg.strong[t])} strengths for {len(weak)} weaknesses (as many of each)")
    for s in cfg.species.values():
        where = f"species {s.id}"
        types = [s.type, s.type2] + [t for b in s.branches for t in (b.type, b.type2)]
        if any(t is not None and t not in cfg.types for t in types) or s.type == s.type2 or any(b.type == b.type2 for b in s.branches):
            raise ConfigError(f"{where}: unknown type, or the same type twice")
        if len(s.names) != len(cfg.stages) - 1:
            raise ConfigError(f"{where}: one name per stage before the final form ({len(cfg.stages) - 1})")
        if not s.branches or any(b.metric not in METRICS or b.reference <= 0 for b in s.branches):
            raise ConfigError(f"{where}: branches need a metric among {METRICS} and a positive reference")
        if any(v <= 0 for v in s.base.values()):
            raise ConfigError(f"{where}: base stats must be positive")
        if s.rarity is not None and s.rarity not in RARITIES:
            raise ConfigError(f"{where}: rarity among {sorted(RARITIES)}")
        stage_ids = {st.id for st in cfg.stages}
        for a in s.abilities:
            if a.kind not in ABILITY_KINDS or a.stage not in stage_ids or (a.branch and not s.branch(a.branch)):
                raise ConfigError(f"{where}: ability {a.id} needs a kind among {ABILITY_KINDS}, a known stage and branch")
            if a.kind in ("strike", "drain") and a.power <= 0 or a.kind != "strike" and a.value <= 0:
                raise ConfigError(f"{where}: ability {a.id} needs a positive power (strikes) or value")
    for item in cfg.shop.values():
        where = f"shop item {item.id}"
        if item.price_points is None and item.price_gems is None:
            raise ConfigError(f"{where}: a price in points or in gems")
        if any(p is not None and p <= 0 for p in (item.price_points, item.price_gems)):
            raise ConfigError(f"{where}: prices must be positive")
        if item.random and item.price_gems is not None:
            raise ConfigError(f"{where}: a random item can only be paid in points (never gems nor real money)")
        if item.kind == "pet" and (item.species not in cfg.species or cfg.species[item.species].starter):
            raise ConfigError(f"{where}: a known species, not a starter (starters are never sold)")
    for pack in cfg.gem_packs.values():
        if pack.gems <= 0 or pack.price_eur <= 0:
            raise ConfigError(f"gem pack {pack.id}: gems and price must be positive")


@lru_cache(maxsize=1)
def default() -> GameConfig:
    return load()
