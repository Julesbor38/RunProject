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


def test_starter_is_chosen_once_for_good(game):
    pet = game.pets.choose_starter("jules", "galet")
    assert pet.active and pet.name == "Galet" and pet.stage == 0 and pet.level == 1
    with pytest.raises(GameError, match="définitif"):
        game.pets.choose_starter("jules", "fusette")
    with pytest.raises(GameError):
        game.pets.choose_starter("marie", "unknown")
    assert len(game.pets.all("jules")) == 1 and game.pets.choose_starter("marie", "foulon", "  Ma  Foulée ").name == "Ma Foulée"


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
        assert c.post("/api/game/starter", json={"species": "galet"}).status_code == 409
        r = c.post(f"/api/game/pets/{pet['id']}/levels", json={"count": 1, "request_id": "req-00001"})
        assert r.status_code == 402 and "points insuffisants" in r.json()["detail"]
        give(g, "tester", 100)
        out = c.post(f"/api/game/pets/{pet['id']}/levels", json={"count": "max", "request_id": "req-00002"}).json()
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
