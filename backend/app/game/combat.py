"""Turn-based combat against bots (solo, or a team of 3 against 3), resolved by the server only.

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
# weather -> (type favoured, types hindered)
WEATHERS = {"rain": ("pluvieux", ("ensoleille",)), "sun": ("ensoleille", ("pluvieux", "glace")), "snow": ("glace", ("ensoleille",))}
WEATHER_NAMES = {"rain": "La pluie tombe", "sun": "Le soleil tape", "snow": "Il neige"}
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
    weather: str = ""  # rain, sun, snow: set for weather_turns
    weather_turns: int = 4
    freeze: int = 0  # % chance that the target misses its next action
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
        if m.weather and m.weather not in WEATHERS:
            raise ConfigError(f"moves: {m.id}: weather among {sorted(WEATHERS)}")
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
    type2: str | None = None
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
    weather: dict | None = None  # {"kind": rain | sun | snow, "turns": n}

    def by_id(self, fid: str) -> Fighter | None:
        return next((f for f in self.fighters if f.id == fid), None)

    @property
    def player(self) -> Fighter:
        """The first of the player's side (solo: the only one)."""
        return next(f for f in self.fighters if f.side == "player")

    def side_of(self, side: str) -> list[Fighter]:
        return [f for f in self.fighters if f.side == side]

    def alive(self, side: str) -> list[Fighter]:
        return [f for f in self.fighters if f.side == side and f.alive]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Battle:
        d = copy.deepcopy(d)
        return Battle(**{**d, "fighters": [Fighter(**f) for f in d["fighters"]]})


def _moves_of(game: GameConfig, bc: BattleConfig, sp: Species, stage: int, branch: str | None, type_: str, specials: bool,
              type2: str | None = None) -> tuple[list[str], dict[str, Move]]:
    kit = bc.kit(type_)
    if type2:  # two types: both attacks of the first, the first attack of the second, the first's defence
        kit = kit[:2] + [bc.kit(type2)[0], kit[2]]
    extra = {}
    if specials:
        for a in sp.abilities:
            if stage >= game.stage_index(a.stage) and (not a.branch or a.branch == branch):
                m = ability_move(game, sp, branch, a)
                extra[m.id] = m
    return [m.id for m in kit] + list(extra), extra


def player_fighter(game: GameConfig, bc: BattleConfig, pet, stats: dict, type_: str, form: str, fid: str = "p", side: str = "player",
                   type2: str | None = None) -> Fighter:
    sp = game.species[pet.species]
    if type2 is None:
        b = sp.branch(pet.branch)
        type2 = b.type2 if b else sp.type2
    moves, _ = _moves_of(game, bc, sp, pet.stage, pet.branch, type_, specials=True, type2=type2)
    hp = round(stats["hp"] * bc.p["hp_factor"])
    return Fighter(fid, side, pet.name, sp.id, pet.stage, pet.branch, type_, hp, hp, stats["attack"], stats["defense"], stats["speed"],
                   moves, level=pet.level, type2=type2)


def _enemy(game: GameConfig, bc: BattleConfig, fid: str, species: str, stage: int, branch: str | None, scale: float,
           extra: dict | None, name: str, boss: str | None = None, summon: str | None = None) -> Fighter:
    sp = game.species[species]
    b = sp.branch(branch)
    type_ = b.type if b else sp.type
    type2 = b.type2 if b else sp.type2
    # as strong as a starter, whatever its species (its own spread of stats); a boss then gets its own scale
    scale *= bc.p["mob_total"] / sum(sp.base.values())
    k = {s: scale * (extra or {}).get(s, 1.0) for s in ("hp", "attack", "defense", "speed")}
    st = {s: max(1, round(sp.base[s] * k[s])) for s in k}
    hp = round(st["hp"] * bc.p["hp_factor"])
    moves, _ = _moves_of(game, bc, sp, stage, branch, type_, specials=boss is not None, type2=type2)
    return Fighter(fid, "enemy", name, species, stage, branch, type_, hp, hp, st["attack"], st["defense"], st["speed"], moves,
                   boss=boss, summon=summon, type2=type2)


def level_kind(level: int) -> str:
    return "boss" if level % 10 == 0 else "mid_boss" if level % 5 == 0 else "mobs"


def _scale(bc: BattleConfig, level: int) -> float:
    return bc.p["base_scale"] + bc.p["per_level"] * level


def _mob_stage(bc: BattleConfig, level: int) -> int:
    return min(3, 1 + level // bc.p["mob_stage_every"])


def _wild_name(game: GameConfig, species: str, stage: int) -> str:
    return f"{game.species[species].names[stage]} sauvage"


def enemies_for(game: GameConfig, bc: BattleConfig, level: int, team: bool = False) -> list[Fighter]:
    """The enemies of a level, always the same for that level. `team`: the team trail, three against three
    (three mobs, or the boss and two guards)."""
    if team:
        return _team_enemies(game, bc, level)
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


def _team_enemies(game: GameConfig, bc: BattleConfig, level: int) -> list[Fighter]:
    rng = random.Random(f"team:{level}")
    k = _scale(bc, level) * bc.p["team_scale"]
    stage = _mob_stage(bc, level)
    out = []
    if level_kind(level) != "mobs":
        boss = enemies_for(game, bc, level)[0]
        out.append(_enemy(game, bc, "e1", boss.species, boss.stage, boss.branch, k, bc.p["boss_scale" if boss.boss == "big" else "mid_boss_scale"],
                          boss.name, boss=boss.boss, summon=boss.summon))
        guards = k * bc.p["team_guard_scale"]
        for i in (2, 3):
            species = rng.choice(bc.mob_species)
            out.append(_enemy(game, bc, f"e{i}", species, stage, None, guards, None, f"Garde {_wild_name(game, species, stage).removesuffix(' sauvage')}"))
        return out
    for i in (1, 2, 3):
        species = rng.choice(bc.mob_species)
        out.append(_enemy(game, bc, f"e{i}", species, stage, None, k, None, _wild_name(game, species, stage)))
    return out


def new_battle(game: GameConfig, bc: BattleConfig, level: int, player: Fighter | list[Fighter], seed: str, team: bool = False) -> Battle:
    players = player if isinstance(player, list) else [player]
    return Battle(seed, level, players + enemies_for(game, bc, level, team))


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
    """Against bots: the player's move (and target, against a group), then the mobs'. Returns the events, in order."""
    return play_round(game, bc, b, {b.player.id: (move_id, target_id)})


def check_choice(game: GameConfig, bc: BattleConfig, b: Battle, fid: str, move_id: str) -> None:
    f = b.by_id(fid)
    if f is None or not f.alive:
        raise InvalidAction("ce combattant ne peut plus jouer")
    if move_id not in f.moves:
        raise InvalidAction("ton familier ne connaît pas cette attaque")
    if f.cooldowns.get(move_id, 0) > 0:
        raise InvalidAction(f"pas encore prête : encore {f.cooldowns[move_id]} tour(s)")


def play_round(game: GameConfig, bc: BattleConfig, b: Battle, choices: dict[str, tuple[str, str | None]]) -> list[dict]:
    """One round: the fighters in `choices` play their move (and target), the AI plays for the others (the mobs,
    or a friend who did not play in time). Returns the events, in order."""
    if b.status != "running":
        raise InvalidAction("le combat est terminé")
    for fid, (move_id, _) in choices.items():
        check_choice(game, bc, b, fid, move_id)
    rng = random.Random(f"{b.seed}:{b.turn}")
    events: list[dict] = [{"t": "turn", "turn": b.turn}]
    actions = []
    for f in [x for x in b.fighters if x.alive]:
        foes = b.alive("enemy" if f.side == "player" else "player")
        if f.id in choices:
            move_id, target_id = choices[f.id]
            target = b.by_id(target_id) if target_id else None
            if target is None or target.side == f.side or not target.alive:
                target = foes[0]
            actions.append((f, move_of(game, bc, f, move_id), target))
        else:
            actions.append((f, _ai_move(game, bc, b, f, rng), _ai_target(foes, rng)))
    tiebreak = {id(a[0]): rng.random() for a in actions}
    actions.sort(key=lambda a: (not a[1].priority, -_eff_speed(a[0]), tiebreak[id(a[0])]))
    for actor, move, tgt in actions:
        if not actor.alive or b.status != "running":
            continue
        if actor.effects.pop("frozen", None):
            events.append({"t": "frozen", "target": actor.id, "name": actor.name})
            continue
        _act(game, bc, b, actor, move, tgt, rng, events)
        _check_end(b, events)
    if b.status == "running":
        _end_of_round(b, events, bc)
        if b.weather:
            b.weather["turns"] -= 1
            if b.weather["turns"] <= 0:
                b.weather = None
                events.append({"t": "weather", "weather": None, "text": "Le temps se calme"})
        _check_end(b, events)
    if b.status == "running":
        b.turn += 1
        if b.turn > bc.p["max_turns"]:
            b.status, b.end_reason = "lost", "à bout de souffle"
            events.append({"t": "end", "result": "lost", "reason": b.end_reason})
    return events


def _ai_target(foes: list[Fighter], rng: random.Random) -> Fighter:
    """The weakest one most of the time (finish it off), anyone otherwise."""
    if len(foes) > 1 and rng.random() < 0.6:
        return min(foes, key=lambda f: f.hp / f.max_hp)
    return rng.choice(foes)


def ai_choice(game: GameConfig, bc: BattleConfig, b: Battle, fid: str) -> str:
    """The move the AI would play for this fighter now (a friend who did not play in time)."""
    return _ai_move(game, bc, b, b.by_id(fid), random.Random(f"{b.seed}:{b.turn}:{fid}")).id


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
            dmg, crit, eff = _damage(game, bc, actor, t, move, rng, _weather_factor(bc, b, move.type))
            t.hp = max(0, t.hp - dmg)
            dealt += dmg
            events.append({"t": "hit", "target": t.id, "dmg": dmg, "crit": crit, "eff": eff, "hp": t.hp})
            if not t.alive:
                events.append({"t": "ko", "target": t.id, "name": t.name})
        if t.alive and move.dot:
            t.effects["dot"] = {"pct": move.dot, "turns": move.dot_turns, "type": move.type}
            events.append({"t": "status", "target": t.id, "status": "dot", "turns": move.dot_turns})
        if t.alive and move.freeze and "glace" not in (t.type, t.type2) and rng.random() * 100 < move.freeze:
            t.effects["frozen"] = {"turns": 1}
            events.append({"t": "status", "target": t.id, "status": "frozen"})
        if t.alive:
            _phase(game, bc, b, t, events)
    if move.drain and dealt and actor.alive:
        _heal(actor, round(dealt * move.drain / 100), events)
    if move.weather:
        _set_weather(b, move.weather, move.weather_turns, events)


def _set_weather(b: Battle, kind: str, turns: int, events: list) -> None:
    b.weather = {"kind": kind, "turns": turns}
    events.append({"t": "weather", "weather": kind, "turns": turns, "text": WEATHER_NAMES[kind]})


def _weather_factor(bc: BattleConfig, b: Battle, move_type: str) -> float:
    if not b.weather:
        return 1.0
    favoured, hindered = WEATHERS[b.weather["kind"]]
    return bc.p["weather_boost"] if move_type == favoured else bc.p["weather_malus"] if move_type in hindered else 1.0


def _damage(game: GameConfig, bc: BattleConfig, a: Fighter, t: Fighter, move: Move, rng: random.Random, weather: float = 1.0) -> tuple[int, bool, str]:
    att = a.attack * (1.3 if a.angry else 1.0)
    guard = t.effects.get("guard")
    dfn = t.defense * (1 + guard["pct"] / 100 if guard else 1)
    eff = game.effectiveness(move.type, t.type, t.type2)
    spread = bc.p["random_spread"] / 100
    crit = rng.random() * 100 < bc.p["crit_chance"] + move.crit
    dmg = move.power / 100 * att * (att / (att + dfn)) * 2 * bc.p["damage_scale"] * eff * rng.uniform(1 - spread, 1 + spread)
    dmg *= weather
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


def _end_of_round(b: Battle, events: list, bc: BattleConfig | None = None) -> None:
    w = b.weather["kind"] if b.weather else None
    for f in [x for x in b.fighters if x.alive]:
        if bc and w == "rain" and "pluvieux" in (f.type, f.type2):
            _heal(f, round(f.max_hp * bc.p["rain_heal"] / 100), events)
        if bc and w == "snow" and "glace" not in (f.type, f.type2):
            dmg = max(1, round(f.max_hp * bc.p["snow_chip"] / 100))
            f.hp = max(0, f.hp - dmg)
            events.append({"t": "hit", "target": f.id, "dmg": dmg, "crit": False, "eff": "", "hp": f.hp, "dot": True, "weather": "snow"})
            if not f.alive:
                events.append({"t": "ko", "target": f.id, "name": f.name})
                continue
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
    if not b.alive("player"):
        b.status, b.end_reason = "lost", "K.O."
        events.append({"t": "end", "result": "lost", "reason": b.end_reason})
    elif not b.alive("enemy"):
        b.status = "won"
        events.append({"t": "end", "result": "won"})


def replay(game: GameConfig, bc: BattleConfig, initial: dict, actions: list) -> Battle:
    """The same battle again from its initial state and the moves played (debugging, checks): against bots a list
    of (move, target), between friends a list of {fighter id: (move, target)} per round."""
    b = Battle.from_dict(initial)
    for a in actions:
        if isinstance(a, dict):
            play_round(game, bc, b, {k: tuple(v) for k, v in a.items()})
        else:
            play_turn(game, bc, b, *a)
    return b


# --- what the client shows ---


def fighter_view(game: GameConfig, bc: BattleConfig, f: Fighter, mine: str = "player") -> dict:
    """A fighter as the client shows it; `mine`: the engine side of the viewer (its fighters show as "player",
    with their moves; between friends, the one who was challenged plays the engine's "enemy" side)."""
    sp = game.species[f.species]
    side = "player" if f.side == mine else "enemy"
    out = {"id": f.id, "side": side, "name": f.name, "species": f.species, "stage": f.stage, "branch": f.branch, "type": f.type,
           "type_name": game.types[f.type], "type2": f.type2,
           "type2_name": game.types[f.type2] if f.type2 else None, "color": sp.color, "hp": f.hp, "max_hp": f.max_hp, "boss": f.boss, "angry": f.angry,
           "level": f.level, "effects": sorted(f.effects), "power": f.attack + f.defense + f.speed + f.max_hp // 3}
    if side == "player":
        out["moves"] = []
        for m_id in f.moves:
            m = move_of(game, bc, f, m_id)
            out["moves"].append({"id": m.id, "name": m.name, "type": m.type, "kind": m.kind, "target": m.target, "anim": m.anim,
                                 "description": m.description, "power": m.power, "hits": m.hits, "cooldown": f.cooldowns.get(m.id, 0),
                                 "priority": m.priority})
    return out


def battle_view(game: GameConfig, bc: BattleConfig, b: Battle, mine: str = "player") -> dict:
    return {"level": b.level, "kind": level_kind(b.level), "turn": b.turn, "max_turns": bc.p["max_turns"], "status": b.status,
            "end_reason": b.end_reason, "weather": b.weather, "fighters": [fighter_view(game, bc, f, mine) for f in b.fighters]}

