"""Game configuration: the TOML files of config/ (stages and level costs, types, species), loaded and checked
once. Editing a file and restarting the API is enough (see README.md)."""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"
STATS = ("hp", "attack", "defense", "speed")
METRICS = ("ascent_per_km", "night_share", "long_share", "fast_share", "new_share")


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

    @property
    def final(self) -> int:
        return len(self.stages) - 1

    def level_cost(self, level: int) -> int:
        """Points to reach `level` from the one below."""
        return math.ceil(self.cost_base * level**self.cost_exponent)

    def levels_cost(self, current: int, target: int) -> int:
        return sum(self.level_cost(n) for n in range(current + 1, target + 1))

    def effectiveness(self, attacker: str, defender: str) -> float:
        if defender in self.strong.get(attacker, ()):
            return self.strong_multiplier
        if attacker in self.strong.get(defender, ()):
            return self.weak_multiplier
        return 1.0

    def starters(self) -> list[Species]:
        return [s for s in self.species.values() if s.starter]


def _read(name: str, folder: Path) -> dict:
    with open(folder / name, "rb") as f:
        return tomllib.load(f)


def load(folder: Path = CONFIG_DIR) -> GameConfig:
    st, ty, sp = _read("stages.toml", folder), _read("types.toml", folder), _read("species.toml", folder)
    stages = tuple(Stage(i, s["id"], s["name"], int(s["max_level"]), int(s["evolve_cost"]), float(s["stat_multiplier"]))
                   for i, s in enumerate(st["stage"]))
    types = dict(ty["names"])
    strong = {t: frozenset(ty["strong"].get(t, ())) for t in types}
    species = {}
    for s in sp["species"]:
        branches = tuple(Branch(b["id"], b["name"], b["type"], b["metric"], float(b["reference"]), b.get("hint", "")) for b in s["branch"])
        species[s["id"]] = Species(s["id"], s["type"], tuple(s["names"]), {k: int(s["base"][k]) for k in STATS}, branches,
                                   bool(s.get("starter", False)), s.get("color", "#888888"), s.get("description", ""))
    cfg = GameConfig(stages, float(st["levels"]["cost_base"]), float(st["levels"]["cost_exponent"]),
                     float(st["levels"]["stat_bonus_per_level"]), types, strong,
                     float(ty["strong_multiplier"]), float(ty["weak_multiplier"]), species)
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
    for s in cfg.species.values():
        where = f"species {s.id}"
        if s.type not in cfg.types or any(b.type not in cfg.types for b in s.branches):
            raise ConfigError(f"{where}: unknown type")
        if len(s.names) != len(cfg.stages) - 1:
            raise ConfigError(f"{where}: one name per stage before the final form ({len(cfg.stages) - 1})")
        if not s.branches or any(b.metric not in METRICS or b.reference <= 0 for b in s.branches):
            raise ConfigError(f"{where}: branches need a metric among {METRICS} and a positive reference")
        if any(v <= 0 for v in s.base.values()):
            raise ConfigError(f"{where}: base stats must be positive")


@lru_cache(maxsize=1)
def default() -> GameConfig:
    return load()
