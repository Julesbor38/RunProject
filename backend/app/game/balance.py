"""Balancing: the cost of every level from 1 to 100 (and of the evolutions on the way) and the stats of each
starter at that level, from the current config/. Run: python -m app.game.balance [species ...]"""
from __future__ import annotations

import sys

from . import config
from .pets import stats


def main(argv: list[str]) -> None:
    cfg = config.default()
    species = [cfg.species[s] for s in argv] if argv else cfg.starters()
    head = f"{'niv':>3} {'stade':<13} {'coût':>6} {'cumul':>8}  " + "  ".join(f"{s.id + ' (PV/Att/Déf/Vit)':<26}" for s in species)
    print(head)
    print("-" * len(head))
    total, stage = 0, 0
    for level in range(1, cfg.stages[-1].max_level + 1):
        cost = 0
        if level > 1:
            cost = cfg.level_cost(level)
            total += cost
        while level > cfg.stages[stage].max_level:  # evolve first: bought at the previous stage's max level
            stage += 1
            total += cfg.stages[stage].evolve_cost
            print(f"{'':>3} -> {cfg.stages[stage].name:<10} {cfg.stages[stage].evolve_cost:>6} {_n(total - cost):>8}  (évolution)")
        cols = "  ".join(f"{'/'.join(str(v) for v in stats(cfg, s, stage, level).values()):<26}" for s in species)
        print(f"{level:>3} {cfg.stages[stage].name:<13} {cost:>6} {_n(total):>8}  {cols}")
    print(f"Total du niveau 1 au niveau {cfg.stages[-1].max_level}, évolutions comprises : {_n(total)} points")


def _n(v: int) -> str:
    return f"{v:,}".replace(",", " ")


if __name__ == "__main__":
    main(sys.argv[1:])
