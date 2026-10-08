"""Turn-based combat against bots, resolved by the server only.

A battle is a plain state (fighters, turn, status) that `play_turn` moves forward: the player's move, then the
mobs' (chosen by a small AI), in order of priority then speed; damage from attack, defence, type effectiveness,
a bounded random spread and rare critical blows; effects (guard, dodge, regen, damage over time, haste) that
last a few turns; bosses that change phase at half HP (a big boss also calls reinforcements).

Deterministic: the randomness of each turn comes from Random(f"{seed}:{turn}"), so the same seed and the same
moves always give the same battle (`replay`). Config: config/moves.toml (type kits) and config/battles.toml.
"""
from __future__ import annotations

import copy
import random
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import CONFIG_DIR, ConfigError, GameConfig, Species

ATTACK_FIELDS = ("power",)
DEFENCE_FIELDS = ("guard", "dodge", "heal", "regen", "haste")


@dataclass(frozen=True)
class Move:
    id: str
    name: str
    type: str
    power: int = 0  # 0: not an attack
    target: str = "one"  # one, all
    hits: int = 1
    priority: bool = False
    crit: int = 0
    drain: int = 0
    dot: int = 0
    dot_turns: int = 0
    guard: int = 0
    dodge: int = 0
    heal: int = 0
    regen: int = 0
    haste: int = 0
    turns: int = 2
    anim: str = ""
    description: str = ""
    special: bool = False  # a species ability (cooldown)

    @property
    def kind(self) -> str:
        return "special" if self.special else "attack" if self.power else "defense"


@dataclass(frozen=True)
class Boss:
    name: str
    species: str
    stage: str
    branch: str | None = None
    summon: str | None = None


@dataclass(frozen=True)
class BattleConfig:
    moves: dict[str, Move]
    kits: dict[str, tuple[tuple[str, str], str]]  # type -> ((attack, attack), defence)
    special_cooldown: int
    defense_cooldown: int
    p: dict  # the numbers of battles.toml
    mob_species: tuple[str, ...]
    mid_bosses: tuple[Boss, ...]
    bosses: tuple[Boss, ...]

    def kit(self, type_: str) -> list[Move]:
        (a1, a2), d = self.kits[type_]
        return [self.moves[a1], self.moves[a2], self.moves[d]]


def load_battle(game: GameConfig, folder: Path = CONFIG_DIR) -> BattleConfig:
    with open(folder / "moves.toml", "rb") as f:
        mv = tomllib.load(f)
    with open(folder / "battles.toml", "rb") as f:
        bt = tomllib.load(f)
    fields = Move.__dataclass_fields__
    moves = {m["id"]: Move(**{k: v for k, v in m.items() if k in fields}) for m in mv["move"]}
    kits = {t: ((k["attacks"][0], k["attacks"][1]), k["defense"]) for t, k in mv["kits"].items()}
    boss = lambda b: Boss(b["name"], b["species"], b["stage"], b.get("branch"), b.get("summon"))  # noqa: E731
    params = {k: v for k, v in bt.items() if not isinstance(v, list) or k == "mob_species"}
    cfg = BattleConfig(moves, kits, int(mv.get("special_cooldown", 3)), int(mv.get("defense_cooldown", 1)), params, tuple(bt["mob_species"]),
                       tuple(boss(b) for b in bt["mid_boss"]), tuple(boss(b) for b in bt["boss"]))
    _validate(cfg, game)
    return cfg


def _validate(cfg: BattleConfig, game: GameConfig) -> None:
    if set(cfg.kits) != set(game.types):
        raise ConfigError("moves: one kit per type")
    for t, ((a1, a2), d) in cfg.kits.items():
        for m in (a1, a2, d):
            if m not in cfg.moves or cfg.moves[m].type != t:
                raise ConfigError(f"moves: kit {t}: {m} unknown or of another type")
        if not (cfg.moves[a1].power and cfg.moves[a2].power) or cfg.moves[d].power:
            raise ConfigError(f"moves: kit {t}: two attacks (power) and one defence (no power)")
        if not any(getattr(cfg.moves[d], k) for k in DEFENCE_FIELDS):
            raise ConfigError(f"moves: kit {t}: the defence needs guard, dodge, heal, regen or haste")
    for m in cfg.moves.values():
        if m.target not in ("one", "all") or m.hits < 1:
            raise ConfigError(f"moves: {m.id}: target one or all, hits >= 1")
    for sp in cfg.mob_species + tuple(b.species for b in cfg.mid_bosses + cfg.bosses) + tuple(b.summon for b in cfg.bosses if b.summon):
        if sp not in game.species:
            raise ConfigError(f"battles: unknown species {sp}")
    for b in cfg.mid_bosses + cfg.bosses:
        game.stage_index(b.stage)
        if b.branch and not game.species[b.species].branch(b.branch):
            raise ConfigError(f"battles: {b.name}: unknown branch {b.branch}")


_loaded: dict[int, BattleConfig] = {}


def default(game: GameConfig) -> BattleConfig:
    if id(game) not in _loaded:
        _loaded[id(game)] = load_battle(game)
    return _loaded[id(game)]


def ability_move(game: GameConfig, sp: Species, branch: str | None, ability) -> Move:
    """A species ability as a combat move (with a cooldown)."""
    b = sp.branch(branch)
    type_ = b.type if (b and ability.stage == "final") else sp.type
    kw = dict(id=f"sp:{ability.id}", name=ability.name, type=type_, description=ability.description, special=True, anim=f"special-{type_}")
    if ability.kind == "strike":
        return Move(power=ability.power, **kw)
    if ability.kind == "drain":
        return Move(power=ability.power, drain=ability.value, **kw)
    if ability.kind == "guard":
        return Move(guard=ability.value, turns=2, **kw)
    if ability.kind == "heal":
        return Move(heal=ability.value, **kw)
    return Move(haste=ability.value, turns=2, **kw)


# --- fighters and battles ---


@dataclass
class Fighter:
    id: str
    side: str  # player, enemy
    name: str
    species: str
    stage: int
    branch: str | None
    type: str
    max_hp: int
    hp: int
    attack: int
    defense: int
    speed: int
    moves: list[str]  # move ids: the type kit, then the unlocked specials ("sp:…")
    level: int | None = None
    boss: str | None = None  # mid, big
    summon: str | None = None
    phase: int = 1
    angry: bool = False
    cooldowns: dict[str, int] = field(default_factory=dict)
    effects: dict[str, dict] = field(default_factory=dict)  # guard, dodge, regen, dot, haste

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Battle:
    seed: str
    level: int
    fighters: list[Fighter]
    turn: int = 1
    status: str = "running"  # running, won, lost
    end_reason: str = ""

    def by_id(self, fid: str) -> Fighter | None:
        return next((f for f in self.fighters if f.id == fid), None)

    @property
    def player(self) -> Fighter:
        return next(f for f in self.fighters if f.side == "player")

    def alive(self, side: str) -> list[Fighter]:
        return [f for f in self.fighters if f.side == side and f.alive]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Battle:
        d = copy.deepcopy(d)
        return Battle(**{**d, "fighters": [Fighter(**f) for f in d["fighters"]]})


def _moves_of(game: GameConfig, bc: BattleConfig, sp: Species, stage: int, branch: str | None, type_: str, specials: bool) -> tuple[list[str], dict[str, Move]]:
    kit = bc.kit(type_)
    extra = {}
    if specials:
        for a in sp.abilities:
            if stage >= game.stage_index(a.stage) and (not a.branch or a.branch == branch):
                m = ability_move(game, sp, branch, a)
                extra[m.id] = m
    return [m.id for m in kit] + list(extra), extra


def player_fighter(game: GameConfig, bc: BattleConfig, pet, stats: dict, type_: str, form: str) -> Fighter:
    sp = game.species[pet.species]
    moves, _ = _moves_of(game, bc, sp, pet.stage, pet.branch, type_, specials=True)
    hp = round(stats["hp"] * bc.p["hp_factor"])
    return Fighter("p", "player", pet.name, sp.id, pet.stage, pet.branch, type_, hp, hp, stats["attack"], stats["defense"], stats["speed"],
                   moves, level=pet.level)


def _enemy(game: GameConfig, bc: BattleConfig, fid: str, species: str, stage: int, branch: str | None, scale: float,
           extra: dict | None, name: str, boss: str | None = None, summon: str | None = None) -> Fighter:
    sp = game.species[species]
    b = sp.branch(branch)
    type_ = b.type if b else sp.type
    # as strong as a starter, whatever its species (its own spread of stats); a boss then gets its own scale
    scale *= bc.p["mob_total"] / sum(sp.base.values())
    k = {s: scale * (extra or {}).get(s, 1.0) for s in ("hp", "attack", "defense", "speed")}
    st = {s: max(1, round(sp.base[s] * k[s])) for s in k}
    hp = round(st["hp"] * bc.p["hp_factor"])
    moves, _ = _moves_of(game, bc, sp, stage, branch, type_, specials=boss is not None)
    return Fighter(fid, "enemy", name, species, stage, branch, type_, hp, hp, st["attack"], st["defense"], st["speed"], moves,
                   boss=boss, summon=summon)


def level_kind(level: int) -> str:
    return "boss" if level % 10 == 0 else "mid_boss" if level % 5 == 0 else "mobs"


def _scale(bc: BattleConfig, level: int) -> float:
    return bc.p["base_scale"] + bc.p["per_level"] * level


def _mob_stage(bc: BattleConfig, level: int) -> int:
    return min(3, 1 + level // bc.p["mob_stage_every"])


def _wild_name(game: GameConfig, species: str, stage: int) -> str:
    return f"{game.species[species].names[stage]} sauvage"


def enemies_for(game: GameConfig, bc: BattleConfig, level: int) -> list[Fighter]:
    """The enemies of a level, always the same for that level."""
    rng = random.Random(f"level:{level}")
    k = _scale(bc, level)
    kind = level_kind(level)
    if kind != "mobs":
        bosses = bc.bosses if kind == "boss" else bc.mid_bosses
        i = (level // 10 - 1) if kind == "boss" else (level // 10)
        b = bosses[i % len(bosses)]
        cycle = i // len(bosses)
        name = b.name + (f" {'+' * cycle}" if cycle else "")
        extra = bc.p["boss_scale" if kind == "boss" else "mid_boss_scale"]
        return [_enemy(game, bc, "e1", b.species, game.stage_index(b.stage), b.branch, k, extra, name,
                       boss="big" if kind == "boss" else "mid", summon=b.summon)]
    n = 1
    if level >= 3:
        n += rng.random() < min(0.7, level / 25)
        n += n == 2 and rng.random() < min(0.45, level / 50)
    stage = _mob_stage(bc, level)
    scale = k * (bc.p["group_scale"] if n > 1 else 1.0)
    out = []
    for i in range(n):
        species = rng.choice(bc.mob_species)
        out.append(_enemy(game, bc, f"e{i + 1}", species, stage, None, scale, None, _wild_name(game, species, stage)))
    return out


def new_battle(game: GameConfig, bc: BattleConfig, level: int, player: Fighter, seed: str) -> Battle:
    return Battle(seed, level, [player] + enemies_for(game, bc, level))


def reward_for(bc: BattleConfig, level: int, first: bool) -> int:
    base = bc.p["reward_base"] + bc.p["reward_per_level"] * level
    kind = level_kind(level)
    base *= bc.p["boss_reward"] if kind == "boss" else bc.p["mid_boss_reward"] if kind == "mid_boss" else 1
    return round(base if first else base * bc.p["replay_share"])


# --- a turn ---


class InvalidAction(ValueError):
    pass


def move_of(game: GameConfig, bc: BattleConfig, f: Fighter, move_id: str) -> Move:
    if move_id in bc.moves:
        return bc.moves[move_id]
    sp = game.species[f.species]
    for a in sp.abilities:
        if f"sp:{a.id}" == move_id:
            return ability_move(game, sp, f.branch, a)
    raise InvalidAction(f"attaque inconnue : {move_id}")


def _eff_speed(f: Fighter) -> float:
    h = f.effects.get("haste")
    return f.speed * (1 + h["pct"] / 100 if h else 1)


def play_turn(game: GameConfig, bc: BattleConfig, b: Battle, move_id: str, target_id: str | None = None) -> list[dict]:
    """The player's move (and target, against a group), then the mobs'. Returns the events, in order."""
    if b.status != "running":
        raise InvalidAction("le combat est terminé")
    me = b.player
    if move_id not in me.moves:
        raise InvalidAction("ton familier ne connaît pas cette attaque")
    if me.cooldowns.get(move_id, 0) > 0:
        raise InvalidAction(f"pas encore prête : encore {me.cooldowns[move_id]} tour(s)")
    target = b.by_id(target_id) if target_id else None
    if target is None or target.side != "enemy" or not target.alive:
        target = b.alive("enemy")[0]
    rng = random.Random(f"{b.seed}:{b.turn}")
    events: list[dict] = [{"t": "turn", "turn": b.turn}]
    actions = [(me, move_of(game, bc, me, move_id), target)]
    for e in b.alive("enemy"):
        m = _ai_move(game, bc, b, e, rng)
        actions.append((e, m, me))
    tiebreak = {id(a[0]): rng.random() for a in actions}
    actions.sort(key=lambda a: (not a[1].priority, -_eff_speed(a[0]), tiebreak[id(a[0])]))
    for actor, move, tgt in actions:
        if not actor.alive or b.status != "running":
            continue
        _act(game, bc, b, actor, move, tgt, rng, events)
        _check_end(b, events)
    if b.status == "running":
        _end_of_round(b, events)
        _check_end(b, events)
    if b.status == "running":
        b.turn += 1
        if b.turn > bc.p["max_turns"]:
            b.status, b.end_reason = "lost", "à bout de souffle"
            events.append({"t": "end", "result": "lost", "reason": b.end_reason})
    return events


def _ai_move(game: GameConfig, bc: BattleConfig, b: Battle, f: Fighter, rng: random.Random) -> Move:
    ready = [move_of(game, bc, f, m) for m in f.moves if f.cooldowns.get(m, 0) <= 0]
    attacks = [m for m in ready if m.power]
    defences = [m for m in ready if not m.power]
    if defences and f.hp < f.max_hp * 0.4 and rng.random() < (0.6 if f.boss else 0.35):
        return rng.choice(defences)
    specials = [m for m in attacks if m.special]
    if specials and rng.random() < 0.6:
        return rng.choice(specials)
    return rng.choice(attacks) if attacks else ready[0]


def _act(game: GameConfig, bc: BattleConfig, b: Battle, actor: Fighter, move: Move, target: Fighter, rng: random.Random, events: list) -> None:
    foes = b.alive("enemy" if actor.side == "player" else "player")
    if move.power:
        if move.target == "all":
            targets = foes
        else:
            targets = [target] if target.alive else foes[:1]
    else:
        targets = [actor]
    events.append({"t": "move", "actor": actor.id, "move": move.id, "name": move.name, "type": move.type, "anim": move.anim,
                   "kind": move.kind, "targets": [t.id for t in targets]})
    if move.special:
        actor.cooldowns[move.id] = bc.special_cooldown + 1  # counted down at the end of this round
    elif not move.power and bc.defense_cooldown:
        actor.cooldowns[move.id] = bc.defense_cooldown + 1
    if not move.power:
        _defend(actor, move, events)
        return
    dealt = 0
    for t in targets:
        if t.effects.get("dodge", {}).get("n", 0) > 0:
            t.effects["dodge"]["n"] -= 1
            if t.effects["dodge"]["n"] <= 0:
                t.effects.pop("dodge")
            events.append({"t": "dodge", "target": t.id})
            continue
        for _ in range(move.hits):
            if not t.alive:
                break
            dmg, crit, eff = _damage(game, bc, actor, t, move, rng)
            t.hp = max(0, t.hp - dmg)
            dealt += dmg
            events.append({"t": "hit", "target": t.id, "dmg": dmg, "crit": crit, "eff": eff, "hp": t.hp})
            if not t.alive:
                events.append({"t": "ko", "target": t.id, "name": t.name})
        if t.alive and move.dot:
            t.effects["dot"] = {"pct": move.dot, "turns": move.dot_turns, "type": move.type}
            events.append({"t": "status", "target": t.id, "status": "dot", "turns": move.dot_turns})
        if t.alive:
            _phase(game, bc, b, t, events)
    if move.drain and dealt and actor.alive:
        _heal(actor, round(dealt * move.drain / 100), events)


def _damage(game: GameConfig, bc: BattleConfig, a: Fighter, t: Fighter, move: Move, rng: random.Random) -> tuple[int, bool, str]:
    att = a.attack * (1.3 if a.angry else 1.0)
    guard = t.effects.get("guard")
    dfn = t.defense * (1 + guard["pct"] / 100 if guard else 1)
    eff = game.effectiveness(move.type, t.type)
    spread = bc.p["random_spread"] / 100
    crit = rng.random() * 100 < bc.p["crit_chance"] + move.crit
    dmg = move.power / 100 * att * (att / (att + dfn)) * 2 * bc.p["damage_scale"] * eff * rng.uniform(1 - spread, 1 + spread)
    if crit:
        dmg *= bc.p["crit_multiplier"]
    return max(1, round(dmg)), crit, ("super" if eff > 1 else "weak" if eff < 1 else "")


def _heal(f: Fighter, amount: int, events: list) -> None:
    amount = min(amount, f.max_hp - f.hp)
    if amount > 0:
        f.hp += amount
        events.append({"t": "heal", "target": f.id, "amount": amount, "hp": f.hp})


def _defend(f: Fighter, move: Move, events: list) -> None:
    if move.guard:
        f.effects["guard"] = {"pct": move.guard, "turns": move.turns}
        events.append({"t": "status", "target": f.id, "status": "guard", "turns": move.turns, "pct": move.guard})
    if move.dodge:
        f.effects["dodge"] = {"n": move.dodge}
        events.append({"t": "status", "target": f.id, "status": "dodge"})
    if move.regen:
        f.effects["regen"] = {"pct": move.regen, "turns": move.turns}
        events.append({"t": "status", "target": f.id, "status": "regen", "turns": move.turns})
    if move.haste:
        f.effects["haste"] = {"pct": move.haste, "turns": move.turns}
        events.append({"t": "status", "target": f.id, "status": "haste", "turns": move.turns, "pct": move.haste})
    if move.heal:
        _heal(f, round(f.max_hp * move.heal / 100), events)


def _phase(game: GameConfig, bc: BattleConfig, b: Battle, f: Fighter, events: list) -> None:
    """Below half HP, a boss gets angry (+30 % attack); a big boss also calls two reinforcements."""
    if not f.boss or f.phase > 1 or f.hp > f.max_hp / 2:
        return
    f.phase, f.angry = 2, True
    events.append({"t": "phase", "actor": f.id, "text": f"{f.name} entre en rage !"})
    if f.boss == "big" and f.summon:
        stage = _mob_stage(bc, b.level)
        scale = _scale(bc, b.level) * bc.p["group_scale"] * 0.8
        for _ in range(2):
            n = sum(1 for x in b.fighters if x.side == "enemy") + 1
            mob = _enemy(game, bc, f"e{n}", f.summon, stage, None, scale, None, _wild_name(game, f.summon, stage))
            b.fighters.append(mob)
            events.append({"t": "summon", "actor": f.id, "fighter": fighter_view(game, bc, mob)})


def _end_of_round(b: Battle, events: list) -> None:
    for f in [x for x in b.fighters if x.alive]:
        dot = f.effects.get("dot")
        if dot:
            dmg = max(1, round(f.max_hp * dot["pct"] / 100))
            f.hp = max(0, f.hp - dmg)
            events.append({"t": "hit", "target": f.id, "dmg": dmg, "crit": False, "eff": "", "hp": f.hp, "dot": True})
            if not f.alive:
                events.append({"t": "ko", "target": f.id, "name": f.name})
                continue
        regen = f.effects.get("regen")
        if regen:
            _heal(f, round(f.max_hp * regen["pct"] / 100), events)
        for key in ("guard", "regen", "dot", "haste"):
            e = f.effects.get(key)
            if e:
                e["turns"] -= 1
                if e["turns"] <= 0:
                    f.effects.pop(key)
        for m in list(f.cooldowns):
            f.cooldowns[m] -= 1
            if f.cooldowns[m] <= 0:
                f.cooldowns.pop(m)


def _check_end(b: Battle, events: list) -> None:
    if b.status != "running":
        return
    if not b.player.alive:
        b.status, b.end_reason = "lost", "K.O."
        events.append({"t": "end", "result": "lost", "reason": b.end_reason})
    elif not b.alive("enemy"):
        b.status = "won"
        events.append({"t": "end", "result": "won"})


def replay(game: GameConfig, bc: BattleConfig, initial: dict, actions: list[tuple[str, str | None]]) -> Battle:
    """The same battle again from its initial state and the player's moves (debugging, checks)."""
    b = Battle.from_dict(initial)
    for move, target in actions:
        play_turn(game, bc, b, move, target)
    return b


# --- what the client shows ---


def fighter_view(game: GameConfig, bc: BattleConfig, f: Fighter) -> dict:
    sp = game.species[f.species]
    out = {"id": f.id, "side": f.side, "name": f.name, "species": f.species, "stage": f.stage, "branch": f.branch, "type": f.type,
           "type_name": game.types[f.type], "color": sp.color, "hp": f.hp, "max_hp": f.max_hp, "boss": f.boss, "angry": f.angry,
           "level": f.level, "effects": sorted(f.effects), "power": f.attack + f.defense + f.speed + f.max_hp // 3}
    if f.side == "player":
        out["moves"] = []
        for m_id in f.moves:
            m = move_of(game, bc, f, m_id)
            out["moves"].append({"id": m.id, "name": m.name, "type": m.type, "kind": m.kind, "target": m.target, "anim": m.anim,
                                 "description": m.description, "power": m.power, "hits": m.hits, "cooldown": f.cooldowns.get(m.id, 0),
                                 "priority": m.priority})
    return out


def battle_view(game: GameConfig, bc: BattleConfig, b: Battle) -> dict:
    return {"level": b.level, "kind": level_kind(b.level), "turn": b.turn, "max_turns": bc.p["max_turns"], "status": b.status,
            "end_reason": b.end_reason, "fighters": [fighter_view(game, bc, f) for f in b.fighters]}

