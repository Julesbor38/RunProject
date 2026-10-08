"""The game: config, wallet (atomic, no double spending), familiers (starter, levels, evolutions, branches), API."""
import threading
from pathlib import Path

import pytest

from app.game import config
from app.game.db import GameDB
from app.game.pets import GameError, choose_branch, profile_metrics
from app.game.service import Game
from app.game.wallet import InsufficientFunds, Wallet

CFG = config.default()


@pytest.fixture
def game(tmp_path):
    return Game(tmp_path / "game.sqlite")


def give(game, user, points):
    game.wallet.credit(user, [{"key": f"gift:{points}:{len(game.wallet.rows(user))}", "amount": points, "kind": "gift"}])


def act(run_km, ascent=0.0, night_km=0.0, fast_km=0.0, new_km=0.0, date="2026-10-01"):
    return {"run_m": run_km * 1000, "ascent_m": ascent, "night_m": night_km * 1000, "fast_m": fast_km * 1000,
            "new_m": new_km * 1000, "date": date}


# --- config ---


def test_types_starter_triangle():
    eff = CFG.effectiveness
    assert eff("montagne", "vitesse") == 1.5 and eff("vitesse", "montagne") == 0.75
    assert eff("vitesse", "endurance") == 1.5 and eff("endurance", "vitesse") == 0.75
    assert eff("endurance", "montagne") == 1.5 and eff("montagne", "endurance") == 0.75
    assert {s.type for s in CFG.starters()} == {"montagne", "vitesse", "endurance"}


def test_every_type_has_a_strength_and_a_weakness_and_same_type_is_neutral():
    for t in CFG.types:
        row = [CFG.effectiveness(t, o) for o in CFG.types]
        col = [CFG.effectiveness(o, t) for o in CFG.types]
        assert 1.5 in row and 0.75 in row and 1.5 in col and CFG.effectiveness(t, t) == 1.0
        assert row.count(1.5) == row.count(0.75)  # balanced: as many good matchups as bad ones


def test_starters_have_the_same_total_spread_differently():
    totals = {s.id: sum(s.base.values()) for s in CFG.starters()}
    assert len(set(totals.values())) == 1
    galet, fusette, foulon = (CFG.species[k].base for k in ("galet", "fusette", "foulon"))
    assert galet["defense"] == max(galet.values()) and fusette["speed"] == max(fusette.values()) and foulon["hp"] == max(foulon.values())
    assert all(len(s.branches) == 2 for s in CFG.starters())


def test_a_broken_config_is_refused(tmp_path):
    for name in ("stages.toml", "species.toml", "types.toml"):
        (tmp_path / name).write_text((config.CONFIG_DIR / name).read_text())
    types = (tmp_path / "types.toml").read_text().replace('nocturne = ["vitesse", "exploration"]', "nocturne = []")
    (tmp_path / "types.toml").write_text(types)
    with pytest.raises(config.ConfigError, match="nocturne"):
        config.load(tmp_path)


def test_level_cost_curve():
    assert CFG.level_cost(2) == 2 and CFG.level_cost(100) == 500  # ceil(0.5 * n^1.5)
    assert CFG.levels_cost(1, 5) == sum(CFG.level_cost(n) for n in range(2, 6))


# --- wallet ---


def test_wallet_never_goes_below_zero_and_keys_count_once(game):
    w = game.wallet
    assert w.credit("jules", [{"key": "a", "amount": 30, "kind": "gift"}, {"key": "a", "amount": 30, "kind": "gift"}]) == 1
    with pytest.raises(InsufficientFunds):
        w.debit("jules", 31, "test", "spend-1", "trop")
    assert w.balance("jules") == 30 and w.debit("jules", 31, "test", "spend-2", "jusqu'au solde", up_to=True) == 30
    assert w.balance("jules") == 0 and w.balance("marie") == 0
    assert [r["balance_after"] for r in w.rows("jules")] == [0, 30]


def test_gems_and_points_are_separate(game):
    game.wallet.credit("jules", [{"key": "mock:1", "amount": 50, "kind": "mock"}], currency="gems")
    assert game.wallet.balances("jules") == {"points": 0, "gems": 50}
    with pytest.raises(InsufficientFunds):
        game.wallet.debit("jules", 1, "test", "x", "x")


def test_no_double_spending_from_two_connections_at_once(tmp_path):
    """Two processes (two connections to the same file) spend the same 100 points at the same time."""
    path = tmp_path / "game.sqlite"
    Wallet(GameDB(path)).credit("jules", [{"key": "gift", "amount": 100, "kind": "gift"}])
    wallets = [Wallet(GameDB(path)) for _ in range(8)]
    results, barrier = [], threading.Barrier(len(wallets))

    def spend(i):
        barrier.wait()
        try:
            results.append(wallets[i].debit("jules", 60, "test", f"spend-{i}", "60"))
        except InsufficientFunds:
            results.append(0)

    threads = [threading.Thread(target=spend, args=(i,)) for i in range(len(wallets))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [0] * 7 + [60] and Wallet(GameDB(path)).balance("jules") == 40


# --- starter ---


def test_each_starter_is_adopted_once_and_they_grow_apart(game):
    galet = game.pets.choose_starter("jules", "galet")
    assert galet.active and galet.name == "Galet" and galet.stage == 0 and galet.level == 1
    with pytest.raises(GameError, match="déjà adopté"):
        game.pets.choose_starter("jules", "galet")
    with pytest.raises(GameError):
        game.pets.choose_starter("marie", "unknown")
    fusette = game.pets.choose_starter("jules", "fusette")
    assert fusette.active and not game.pets.get("jules", galet.id).active  # the newcomer is the active one
    foulon = game.pets.choose_starter("jules", "foulon", "  Ma  Foulée ")
    assert foulon.name == "Ma Foulée" and game.pets.adopted_starters("jules") == {"galet", "fusette", "foulon"}
    give(game, "jules", 10)
    game.pets.buy_levels("jules", fusette.id, 2, "req-00001")
    assert [p.level for p in game.pets.all("jules")] == [1, 3, 1]  # each on its own side
    assert game.pets.activate("jules", galet.id).active and game.pets.active("jules").id == galet.id


# --- levels ---


def test_buying_levels_costs_and_is_atomic(game):
    pet = game.pets.choose_starter("jules", "fusette")
    give(game, "jules", 10)
    pet, spent = game.pets.buy_levels("jules", pet.id, 3, "req-00001")
    assert pet.level == 4 and spent == CFG.levels_cost(1, 4) == 2 + 3 + 4 and game.wallet.balance("jules") == 1
    # retried request: nothing more
    assert game.pets.buy_levels("jules", pet.id, 3, "req-00001")[1] == 0 and game.wallet.balance("jules") == 1
    # not enough for the next one: refused, nothing changes
    with pytest.raises(InsufficientFunds):
        game.pets.buy_levels("jules", pet.id, 1, "req-00002")
    assert game.pets.get("jules", pet.id).level == 4 and game.wallet.balance("jules") == 1


def test_levels_stop_at_the_stage_max(game):
    pet = game.pets.choose_starter("jules", "galet")
    give(game, "jules", 1000)
    with pytest.raises(GameError, match="au plus 4"):  # egg: max level 5, all or nothing
        game.pets.buy_levels("jules", pet.id, 10, "req-00001")
    assert game.wallet.balance("jules") == 1000
    pet, spent = game.pets.buy_levels("jules", pet.id, "max", "req-00002")
    assert pet.level == 5 and spent == CFG.levels_cost(1, 5)
    with pytest.raises(GameError, match="fais-le évoluer"):
        game.pets.buy_levels("jules", pet.id, 1, "req-00003")


def test_max_buys_what_the_points_allow(game):
    pet = game.pets.choose_starter("jules", "galet")
    give(game, "jules", 6)
    pet, spent = game.pets.buy_levels("jules", pet.id, "max", "req-00001")
    assert (pet.level, spent) == (3, 5) and game.wallet.balance("jules") == 1  # 2 + 3, the next one costs 4
    with pytest.raises(GameError, match="points insuffisants"):
        game.pets.buy_levels("jules", pet.id, "max", "req-00002")


# --- evolutions ---


def to_cap(game, user, pet, req):
    give(game, user, CFG.levels_cost(pet.level, CFG.stages[pet.stage].max_level))
    return game.pets.buy_levels(user, pet.id, "max", req)[0]


def test_evolving_needs_the_max_level_and_points_and_never_regresses(game):
    pet = game.pets.choose_starter("jules", "galet")
    with pytest.raises(GameError, match="niveau 5"):
        game.pets.evolve("jules", pet.id, "evo-00001", lambda since: [])
    pet = to_cap(game, "jules", pet, "lvl-00001")
    with pytest.raises(InsufficientFunds):
        game.pets.evolve("jules", pet.id, "evo-00002", lambda since: [])
    give(game, "jules", CFG.stages[1].evolve_cost)
    before = game.pets.stats(pet)
    pet, spent = game.pets.evolve("jules", pet.id, "evo-00003", lambda since: [])
    assert pet.stage == 1 and pet.level == 5 and spent == 50 and game.pets.form_name(pet) == "Galet"
    assert all(game.pets.stats(pet)[k] > before[k] for k in before)
    assert game.pets.evolve("jules", pet.id, "evo-00003", lambda since: [])[0].stage == 1  # retried: nothing more


def test_final_branch_follows_the_running_profile(game):
    sp = CFG.species["galet"]
    hills = [act(10, ascent=400), act(12, ascent=500)]
    night = [act(10, night_km=6), act(8, night_km=8, ascent=30)]
    assert choose_branch(sp, profile_metrics(hills)).id == "cimeval"
    assert choose_branch(sp, profile_metrics(night)).id == "ombrecrete"
    assert choose_branch(sp, profile_metrics([])).id == "cimeval"  # no running: the first branch
    assert choose_branch(CFG.species["foulon"], profile_metrics([act(25), act(5)])).id == "ultravent"
    assert choose_branch(CFG.species["foulon"], profile_metrics([act(8, new_km=6), act(6, new_km=5)])).id == "sentinomade"

    pet = game.pets.choose_starter("jules", "galet")
    for stage in range(1, CFG.final + 1):
        pet = to_cap(game, "jules", pet, f"lvl-{stage:05d}")
        give(game, "jules", CFG.stages[stage].evolve_cost)
        pet = game.pets.evolve("jules", pet.id, f"evo-{stage:05d}", lambda since: night)[0]
    assert pet.stage == CFG.final and pet.branch == "ombrecrete"
    assert game.pets.type_of(pet) == "nocturne" and game.pets.form_name(pet) == "Ombrecrête"
    with pytest.raises(GameError, match="forme finale"):
        game.pets.evolve("jules", pet.id, "evo-99999", lambda since: night)


def test_stats_grow_with_stage_and_level():
    sp = CFG.species["foulon"]
    from app.game.pets import stats

    assert stats(CFG, sp, 2, 1) == sp.base  # young, level 1: the base
    assert stats(CFG, sp, 4, 100)["hp"] == round(sp.base["hp"] * 2.0 * 1.99)


def test_balance_script_prints_the_curves(capsys):
    from app.game import balance

    balance.main([])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 100 and any(l.split()[:1] == ["100"] for l in lines)
    assert f"{CFG.levels_cost(1, 100) + sum(s.evolve_cost for s in CFG.stages):,}".replace(",", " ") in lines[-1]


# --- API ---


def test_game_api_flow_and_privacy(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    g = api.game()
    with TestClient(api.app) as c:
        assert c.get("/api/game").json()["starter_chosen"] is False
        assert [s["id"] for s in c.get("/api/game/starters").json()["starters"]] == ["galet", "fusette", "foulon"]
        pet = c.post("/api/game/starter", json={"species": "foulon", "name": "Tempo"}).json()
        assert pet["name"] == "Tempo" and pet["type"] == "endurance" and pet["active"] and pet["next_level"]["cost"] == 2
        assert pet["next_level"]["affordable"] == 0 and pet["next_level"]["affordable_cost"] == 0
        assert c.post("/api/game/starter", json={"species": "foulon"}).status_code == 409  # already adopted
        assert [s["adopted"] for s in c.get("/api/game/starters").json()["starters"]] == [False, False, True]
        r = c.post(f"/api/game/pets/{pet['id']}/levels", json={"count": 1, "request_id": "req-00001"})
        assert r.status_code == 402 and "points insuffisants" in r.json()["detail"]
        give(g, "tester", 100)
        shown = c.get(f"/api/game/pets/{pet['id']}").json()["next_level"]
        assert shown["affordable"] == 4 and shown["affordable_cost"] == CFG.levels_cost(1, 5)  # what « Max » will cost
        out = c.post(f"/api/game/pets/{pet['id']}/levels", json={"count": "max", "request_id": "req-00002"}).json()
        assert out["spent"] == shown["affordable_cost"]
        assert out["pet"]["level"] == 5 and out["pet"]["evolution"]["ready"] and out["wallet"]["points"] == 100 - out["spent"]
        assert c.post(f"/api/game/pets/{pet['id']}/levels", json={"count": "5", "request_id": "req-00003"}).status_code == 422
        out = c.post(f"/api/game/pets/{pet['id']}/evolve", json={"request_id": "evo-00001"}).json()
        assert out["pet"]["stage"]["id"] == "baby" and out["pet"]["form"] == "Foulon" and out["spent"] == 50
        assert c.patch(f"/api/game/pets/{pet['id']}", json={"name": "Tempo II"}).json()["name"] == "Tempo II"
        tx = c.get("/api/game/transactions").json()
        assert [t["kind"] for t in tx["transactions"]][:2] == ["evolve", "level"] and tx["balance"] == out["wallet"]["points"]
        # someone else's familier does not exist for this account
        other = g.pets.choose_starter("marie", "galet")
        assert c.get(f"/api/game/pets/{other.id}").status_code == 404
        assert c.post(f"/api/game/pets/{other.id}/activate").status_code == 404
        assert c.post(f"/api/game/pets/{other.id}/levels", json={"count": 1, "request_id": "req-00004"}).status_code == 404
    assert g.pets.get("marie", other.id).level == 1 and g.wallet.balance("marie") == 0


def test_branch_preview_from_the_adult_stage(game):
    pet = game.pets.choose_starter("jules", "fusette")
    for stage in range(1, CFG.final):
        pet = to_cap(game, "jules", pet, f"lvl-{stage:05d}")
        give(game, "jules", CFG.stages[stage].evolve_cost)
        pet = game.pets.evolve("jules", pet.id, f"evo-{stage:05d}", lambda since: [])[0]
    view = game.pet_json(pet, 0, [act(10, fast_km=8)])
    assert view["stage"]["id"] == "adult"
    assert [b["name"] for b in view["evolution"]["branches"] if b["leading"]] == ["Éclairon"]
    assert view["evolution"]["cost"] == 3000


# --- shop ---


def test_shop_species_are_stronger_and_have_more_abilities():
    starter_total = max(sum(s.base.values()) for s in CFG.starters())
    for item in CFG.shop.values():
        sp = CFG.species[item.species]
        assert sum(sp.base.values()) > starter_total and sp.rarity and not sp.starter
        assert len(sp.abilities) >= 3 and any(a.stage == "final" for a in sp.abilities)
        assert item.price_points and item.price_gems and not item.random  # deterministic, and earnable by running


def test_a_random_item_paid_in_gems_is_refused(tmp_path):
    for name in ("stages.toml", "species.toml", "types.toml", "shop.toml"):
        (tmp_path / name).write_text((config.CONFIG_DIR / name).read_text())
    with open(tmp_path / "shop.toml", "a") as f:
        f.write('\n[[item]]\nid = "pack"\nkind = "pet"\nspecies = "tempestor"\nrandom = true\nprice_gems = 100\n')
    with pytest.raises(config.ConfigError, match="random item can only be paid in points"):
        config.load(tmp_path)


def test_buying_a_familier_with_points_or_gems(game):
    give(game, "jules", 3500)
    bought = game.shop.buy("jules", "oeuf_colossaure", "points", "buy-00001")
    pet = game.pets.get("jules", bought.pet_id)
    assert (pet.species, pet.stage, pet.level, pet.origin, pet.active) == ("colossaure", 0, 1, "shop", True)
    assert game.wallet.balances("jules") == {"points": 500, "gems": 0} and pet.profile_since is not None
    # the same request again: the same purchase, nothing paid twice
    again = game.shop.buy("jules", "oeuf_colossaure", "points", "buy-00001")
    assert again.replayed and again.pet_id == pet.id and game.wallet.balance("jules") == 500
    # once per account
    with pytest.raises(GameError, match="déjà dans ta collection"):
        game.shop.buy("jules", "oeuf_colossaure", "points", "buy-00002")
    # not enough gems: refused, nothing created
    game.wallet.credit("jules", [{"key": "g", "amount": 599, "kind": "gift"}], currency="gems")
    with pytest.raises(InsufficientFunds):
        game.shop.buy("jules", "oeuf_tempestor", "gems", "buy-00003")
    assert len(game.pets.all("jules")) == 1 and game.wallet.balance("jules", "gems") == 599
    game.wallet.credit("jules", [{"key": "g2", "amount": 1, "kind": "gift"}], currency="gems")
    game.shop.buy("jules", "oeuf_tempestor", "gems", "buy-00004")
    assert game.wallet.balances("jules") == {"points": 500, "gems": 0}  # gems only: points untouched
    assert {p.species for p in game.pets.all("jules")} == {"colossaure", "tempestor"}


def test_two_buyers_at_once_cannot_spend_the_same_points(tmp_path):
    path = tmp_path / "game.sqlite"
    Game(path).wallet.credit("jules", [{"key": "gift", "amount": 6000, "kind": "gift"}])
    games = [Game(path) for _ in range(6)]
    results, barrier = [], threading.Barrier(len(games))

    def buy(i):
        barrier.wait()
        try:
            results.append(games[i].shop.buy("jules", ["oeuf_tempestor", "oeuf_sylvarion"][i % 2], "points", f"buy-{i:05d}").pet_id)
        except (InsufficientFunds, GameError):
            results.append(None)

    threads = [threading.Thread(target=buy, args=(i,)) for i in range(len(games))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r is not None for r in results) == 1 and Game(path).wallet.balance("jules") == 0


def test_gems_need_a_payment_provider(tmp_path):
    from app.game.payments import MockPayments, PaymentError

    off = Game(tmp_path / "off.sqlite")
    with pytest.raises(PaymentError) as e:
        off.shop.buy_gems("jules", "gems_100", "pay-00001")
    assert e.value.status == 503 and off.wallet.balance("jules", "gems") == 0
    mock = Game(tmp_path / "mock.sqlite", payments=MockPayments())
    assert mock.shop.buy_gems("jules", "gems_550", "pay-00001").price == 4.99
    assert mock.shop.buy_gems("jules", "gems_550", "pay-00001").replayed  # once per payment
    assert mock.wallet.balances("jules") == {"points": 0, "gems": 550}


def test_abilities_unlock_with_the_stages(game):
    give(game, "jules", 3000)
    pet = game.pets.get("jules", game.shop.buy("jules", "oeuf_colossaure", "points", "buy-00001").pet_id)
    view = game.pet_json(pet, 0)
    assert view["rarity_name"] == "Rare" and [a["unlocked"] for a in view["abilities"]] == [False, False, False]
    give(game, "jules", CFG.levels_cost(1, 5) + CFG.stages[1].evolve_cost)
    pet = game.pets.buy_levels("jules", pet.id, "max", "lvl-00001")[0]
    pet = game.pets.evolve("jules", pet.id, "evo-00001", lambda since: [])[0]
    assert [a["unlocked"] for a in game.pet_json(pet, 0)["abilities"]] == [True, False, False]


def test_shop_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    g = api.game()
    with TestClient(api.app) as c:
        shop = c.get("/api/game/shop").json()
        assert shop["payments"] == "disabled" and len(shop["items"]) == 5 and not any(i["owned"] for i in shop["items"])
        assert c.post("/api/game/shop/buy", json={"item": "oeuf_aurorelle", "currency": "points", "request_id": "buy-00001"}).status_code == 402
        assert c.post("/api/game/gems/buy", json={"pack": "gems_100", "request_id": "pay-00001"}).status_code == 503
        give(g, "tester", 10000)
        out = c.post("/api/game/shop/buy", json={"item": "oeuf_aurorelle", "currency": "points", "request_id": "buy-00002"}).json()
        assert out["pet"]["species"] == "aurorelle" and out["pet"]["active"] and out["wallet"] == {"points": 0, "gems": 0}
        assert len(out["pet"]["abilities"]) == 4 and out["pet"]["rarity"] == "legendaire"
        assert [i["owned"] for i in c.get("/api/game/shop").json()["items"]] == [False, True, False, False, False]
        assert c.post("/api/game/shop/buy", json={"item": "nope", "currency": "points", "request_id": "buy-00003"}).status_code == 404
        assert c.post("/api/game/shop/buy", json={"item": "oeuf_aurorelle", "currency": "euros", "request_id": "buy-00004"}).status_code == 422
    assert g.shop.owned_species("marie") == set()


# --- battles ---


from app.game import combat  # noqa: E402

BC = combat.default(CFG)


def test_every_type_has_two_attacks_and_a_defence_of_its_own():
    for t in CFG.types:
        kit = BC.kit(t)
        assert [m.kind for m in kit] == ["attack", "attack", "defense"] and {m.type for m in kit} == {t}
        assert len({m.anim for m in kit}) == 3  # an animation each
    assert BC.moves["eboulement"].target == "all" and BC.moves["racines"].regen  # the examples asked for


def test_levels_mobs_groups_and_bosses():
    assert [combat.level_kind(n) for n in (1, 4, 5, 9, 10, 15, 20)] == ["mobs", "mobs", "mid_boss", "mobs", "boss", "mid_boss", "boss"]
    assert len(combat.enemies_for(CFG, BC, 1)) == 1
    assert any(len(combat.enemies_for(CFG, BC, n)) > 1 for n in range(11, 20))  # groups as the levels go up
    mid, big = combat.enemies_for(CFG, BC, 5)[0], combat.enemies_for(CFG, BC, 10)[0]
    assert mid.boss == "mid" and big.boss == "big" and big.summon
    assert combat.enemies_for(CFG, BC, 7)[0].max_hp < combat.enemies_for(CFG, BC, 27)[0].max_hp  # stronger further on
    assert [e.name for e in combat.enemies_for(CFG, BC, 13)] == [e.name for e in combat.enemies_for(CFG, BC, 13)]  # always the same
    assert combat.reward_for(BC, 10, True) == (20 + 40) * 5 and combat.reward_for(BC, 3, False) == round(32 * 0.25)


class _Pet:
    def __init__(self, species, stage, level, branch=None):
        self.species, self.stage, self.level, self.branch, self.name = species, stage, level, branch, "Test"


def fighter(species="foulon", stage=2, level=20, branch=None):
    from app.game.pets import stats

    sp = CFG.species[species]
    b = sp.branch(branch)
    return combat.player_fighter(CFG, BC, _Pet(species, stage, level, branch), stats(CFG, sp, stage, level), b.type if b else sp.type, "x")


def test_a_battle_is_the_same_again_with_the_same_seed():
    def fight(seed):
        b = combat.new_battle(CFG, BC, 3, fighter(), seed)
        initial = b.to_dict()
        moves = []
        while b.status == "running":
            moves.append(("charge_lourde", None))
            combat.play_turn(CFG, BC, b, *moves[-1])
        return initial, moves, b

    initial, moves, b = fight("abc")
    assert combat.replay(CFG, BC, initial, moves).to_dict() == b.to_dict()
    assert fight("abc")[2].to_dict() == b.to_dict()
    assert any(fight(s)[2].to_dict() != b.to_dict() for s in ("x", "y", "z"))  # another seed, another battle


def test_speed_decides_who_strikes_first_and_priority_beats_it():
    b = combat.new_battle(CFG, BC, 1, fighter("galet", 2, 5), "s")
    me, foe = b.player, b.alive("enemy")[0]
    me.speed, foe.speed = 10, 999
    ev = combat.play_turn(CFG, BC, b, "poing_de_granit", None)
    assert [e["actor"] for e in ev if e["t"] == "move"][0] == foe.id
    b2 = combat.new_battle(CFG, BC, 1, fighter("fusette", 2, 5), "s")
    b2.player.speed, b2.alive("enemy")[0].speed = 10, 999
    ev = combat.play_turn(CFG, BC, b2, "eclair", None)  # priority
    assert [e["actor"] for e in ev if e["t"] == "move"][0] == "p"


def test_damage_spread_is_bounded_and_types_matter():
    from random import Random

    a, t = fighter("galet", 2, 20), fighter("fusette", 2, 20)
    t.type = "vitesse"
    poing = BC.moves["poing_de_granit"]
    dmgs = [combat._damage(CFG, BC, a, t, poing, Random(i)) for i in range(300)]
    normal = [d for d, crit, _ in dmgs if not crit]
    assert max(normal) / min(normal) <= 1.1 / 0.9 + 0.05 and all(eff == "super" for _, _, eff in dmgs)  # montagne > vitesse
    assert any(crit for _, crit, _ in dmgs) and sum(crit for _, crit, _ in dmgs) < 60  # rare criticals


def test_defences_dodge_guard_regen_and_cooldown():
    b = combat.new_battle(CFG, BC, 1, fighter("fusette", 2, 20), "s")
    ev = combat.play_turn(CFG, BC, b, "esquive", None)
    assert any(e["t"] == "dodge" and e["target"] == "p" for e in ev) or "dodge" in b.player.effects
    with pytest.raises(combat.InvalidAction, match="pas encore prête"):
        combat.play_turn(CFG, BC, b, "esquive", None)  # a defence waits a turn
    b = combat.new_battle(CFG, BC, 1, fighter("sylvarion", 3, 30), "s")
    combat.play_turn(CFG, BC, b, "racines", None)
    assert b.player.effects["guard"]["pct"] == 40 and b.player.effects["regen"]["pct"] == 6


def test_a_big_boss_gets_angry_and_calls_reinforcements():
    b = combat.new_battle(CFG, BC, 10, fighter("brasaltor", 4, 100, "pyroclaste"), "s")
    boss = b.alive("enemy")[0]
    boss.hp = boss.max_hp // 2 + 1
    events = []
    while b.status == "running" and not any(e["t"] == "summon" for e in events):
        events += combat.play_turn(CFG, BC, b, "poing_de_granit", "e1")
    assert boss.angry and sum(e["t"] == "summon" for e in events) == 2 and len(b.fighters) == 4


def test_trail_rewards_and_daily_limit(game, monkeypatch):
    pet = game.pets.choose_starter("jules", "foulon")
    with pytest.raises(GameError, match="œuf"):
        game.battles.start("jules", 1)
    with game.db.tx() as conn:  # a strong one, to win quickly
        conn.execute("UPDATE pets SET stage = 4, level = 100, branch = 'ultravent' WHERE id = ?", (pet.id,))
    with pytest.raises(GameError, match="pas encore ouvert"):
        game.battles.start("jules", 2)

    def win(level):
        bid, b = game.battles.start("jules", level)
        reward = 0
        while b.status == "running":
            b, _, reward = game.battles.turn("jules", bid, "charge_lourde", None)
        assert b.status == "won"
        return bid, reward

    bid, reward = win(1)
    assert reward == combat.reward_for(game.battles.bc, 1, True) and game.battles.cleared("jules") == 1
    assert game.wallet.balance("jules") == reward and game.battles.check_replay("jules", bid)
    assert win(1)[1] == combat.reward_for(game.battles.bc, 1, False)  # again: a quarter
    monkeypatch.setitem(game.battles.bc.p, "daily_rewarded", 2)
    assert win(2)[1] == 0 and game.battles.cleared("jules") == 2  # over the daily limit: progress, no points
    with pytest.raises(GameError, match="terminé"):
        game.battles.turn("jules", bid, "charge_lourde", None)


def test_battle_api_is_per_user(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    g = api.game()
    pet = g.pets.choose_starter("tester", "galet")
    with g.db.tx() as conn:
        conn.execute("UPDATE pets SET stage = 2, level = 20 WHERE id = ?", (pet.id,))
    with TestClient(api.app) as c:
        trail = c.get("/api/game/battles").json()
        assert trail["cleared"] == 0 and trail["levels"][0]["open"] and not trail["levels"][1]["open"]
        b = c.post("/api/game/battles", json={"level": 1}).json()
        me = next(f for f in b["fighters"] if f["side"] == "player")
        assert [m["id"] for m in me["moves"]][:3] == ["eboulement", "poing_de_granit", "rempart_rocheux"]
        assert c.post(f"/api/game/battles/{b['id']}/turn", json={"move": "nope"}).status_code == 422
        out = c.post(f"/api/game/battles/{b['id']}/turn", json={"move": "eboulement"}).json()
        assert out["events"][0]["t"] == "turn" and any(e["t"] == "move" and e["anim"] == "rockfall" for e in out["events"])
        assert c.get("/api/game/battles").json()["running"] == b["id"]
    g.pets.choose_starter("marie", "fusette")
    with g.db.tx() as conn:
        conn.execute("UPDATE pets SET stage = 2 WHERE user = 'marie'")
    mid, _ = g.battles.start("marie", 1)
    with TestClient(api.app) as c:
        assert c.get(f"/api/game/battles/{mid}").status_code == 404
        assert c.post(f"/api/game/battles/{mid}/turn", json={"move": "eclair"}).status_code == 404


# --- friends and friendly battles ---


def friends_game(tmp_path, *names):
    g = Game(tmp_path / "game.sqlite", exists=lambda n: n in names)
    for n in names:
        pet = g.pets.choose_starter(n, {"jules": "galet", "ethan": "fusette"}.get(n, "foulon"))
        with g.db.tx() as conn:
            conn.execute("UPDATE pets SET stage = 2, level = 20 WHERE id = ?", (pet.id,))
    return g


def test_friend_requests_accept_decline_block(tmp_path):
    g = friends_game(tmp_path, "jules", "ethan", "marie")
    f = g.friends
    with pytest.raises(GameError, match="aucun compte"):
        f.request("jules", "nobody")
    with pytest.raises(GameError, match="toi-même"):
        f.request("jules", "jules")
    assert f.request("jules", "Ethan ") == "pending" and not f.are_friends("jules", "ethan")
    assert f.lists("ethan")["incoming"] == ["jules"] and f.lists("jules")["outgoing"] == ["ethan"]
    with pytest.raises(GameError, match="déjà envoyée"):
        f.request("jules", "ethan")
    f.respond("ethan", "jules", True)
    assert f.are_friends("jules", "ethan") and f.lists("jules")["friends"] == ["ethan"]
    # asking someone who already asked me: friends at once
    f.request("marie", "jules")
    assert f.request("jules", "marie") == "accepted"
    f.remove("jules", "marie")
    assert not f.are_friends("jules", "marie")
    # a block: no more requests, and it does not say who blocked whom
    f.block("marie", "jules")
    with pytest.raises(GameError, match="demande impossible"):
        f.request("jules", "marie")
    assert f.lists("marie")["blocked"] == ["jules"] and f.lists("jules")["blocked"] == []
    f.unblock("marie", "jules")
    assert f.request("jules", "marie") == "pending"


def test_a_friend_sees_familiers_but_no_running_data(tmp_path):
    g = friends_game(tmp_path, "jules", "ethan")
    view = g.friend_json("jules", "ethan")
    assert set(view) == {"name", "record", "pets"} and view["pets"][0]["species"] == "fusette"
    assert not {"wallet", "points", "activities", "communes"} & set(view["pets"][0])


def live(g, mode="normal"):
    g.friends.request("jules", "ethan")
    g.friends.respond("ethan", "jules", True)
    pid = g.pvp.challenge("jules", "ethan", mode)
    assert g.pvp.inbox("ethan")["incoming"][0]["id"] == pid
    g.pvp.accept("ethan", pid)
    return pid


def test_a_live_battle_resolves_once_both_have_played(tmp_path):
    from app.game import pvp

    g = friends_game(tmp_path, "jules", "ethan")
    with pytest.raises(GameError, match="pas \\(encore\\) ton ami"):
        g.pvp.challenge("jules", "ethan", "normal")
    pid = live(g)
    a, b = g.pvp.view("jules", pid), g.pvp.view("ethan", pid)
    # each sees the battle from their own side, with their own moves
    assert next(f for f in a["fighters"] if f["side"] == "player")["id"] == "p"
    assert next(f for f in b["fighters"] if f["side"] == "player")["id"] == "e1"
    assert [m["id"] for m in next(f for f in b["fighters"] if f["side"] == "player")["moves"]][:3] == ["eclair", "rafale_de_coups", "esquive"]
    out = g.pvp.move("jules", pid, "eboulement", None)
    assert out["played"] and not out["friend_played"] and out["round"] == 0
    with pytest.raises(GameError, match="connaît pas"):
        g.pvp.move("ethan", pid, "eboulement", None)  # not one of his moves
    out = g.pvp.move("ethan", pid, "eclair", None)
    assert out["round"] == 1 and not out["played"] and out["rounds"][0]["events"][0]["t"] == "turn"
    assert g.pvp.view("jules", pid, since=1)["rounds"] == []
    # until the end
    while g.pvp.view("jules", pid)["status"] == "running":
        g.pvp.move("jules", pid, "poing_de_granit", None)
        if g.pvp.view("ethan", pid)["status"] == "running":
            g.pvp.move("ethan", pid, "rafale_de_coups", None)
    a, b = g.pvp.view("jules", pid), g.pvp.view("ethan", pid)
    assert {a["result"], b["result"]} in ({"won", "lost"}, {"draw"}) and g.pvp.check_replay(pid)
    rec = g.pvp.record("jules", "ethan")
    assert rec["wins"] + rec["losses"] + rec["draws"] == 1 and g.wallet.balance("jules") == 0  # no points
    assert pvp.MAX_MISSES == 2


def test_who_does_not_play_in_time_loses(tmp_path):
    g = friends_game(tmp_path, "jules", "ethan")
    pid = live(g)

    def late():
        with g.db.tx() as conn:
            conn.execute("UPDATE pvp SET deadline = '2000-01-01T00:00:00+00:00' WHERE id = ?", (pid,))

    g.pvp.move("jules", pid, "eboulement", None)
    late()
    v = g.pvp.view("jules", pid)  # resolved by whoever asks: the AI played for ethan
    assert v["round"] == 1 and v["status"] == "running"
    g.pvp.move("jules", pid, "eboulement", None)
    late()
    v = g.pvp.view("jules", pid)
    assert v["status"] == "done" and v["result"] == "won" and "pas joué à temps" in v["end_reason"]


def test_balanced_mode_and_privacy_of_battles(tmp_path):
    g = friends_game(tmp_path, "jules", "ethan", "marie")
    with g.db.tx() as conn:
        conn.execute("UPDATE pets SET stage = 4, level = 100, branch = 'eclairon' WHERE user = 'ethan'")
    pid = live(g, "balanced")
    fighters = {f["id"]: f for f in g.pvp.view("jules", pid)["fighters"]}
    galet, fusette = CFG.species["galet"], CFG.species["fusette"]
    from app.game.pets import stats

    assert fighters["p"]["max_hp"] == round(stats(CFG, galet, 3, 50)["hp"] * BC.p["hp_factor"])
    assert fighters["e1"]["max_hp"] == round(stats(CFG, fusette, 3, 50)["hp"] * BC.p["hp_factor"])
    with pytest.raises(GameError) as e:
        g.pvp.view("marie", pid)
    assert e.value.status == 404
    with pytest.raises(GameError):
        g.pvp.move("marie", pid, "charge_lourde", None)
    g.pvp.forfeit("ethan", pid)
    assert g.pvp.view("jules", pid)["result"] == "won"


def test_friends_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api, auth
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    monkeypatch.setattr(auth, "users", lambda data_dir: {"tester": {}, "ethan": {}})
    g = api.game()
    with TestClient(api.app) as c:
        assert c.post("/api/game/friends", json={"username": "nobody"}).status_code == 404
        assert c.post("/api/game/friends", json={"username": "ethan"}).json() == {"status": "pending"}
        g.friends.respond("ethan", "tester", True)
        out = c.get("/api/game/friends").json()
        assert [f["name"] for f in out["friends"]] == ["ethan"] and out["pvp"]["running"] is None
        assert c.post("/api/game/pvp", json={"friend": "ethan"}).status_code == 409  # no familier yet
