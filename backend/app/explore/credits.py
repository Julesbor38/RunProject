"""Points (called « crédits » at first), earned by running: km run, new paths and area discovered, places
visited, milestones and badges; and by rating one's activities. Kept in the game's wallet (app/game/wallet.py:
one ledger row per thing that earned points, with a unique key, so that a re-import or a re-processing never
pays twice).

What was run before the account's points began (`history`: everything already there at its first sync, and
later imports of activities older than HISTORY_GRACE before that start) only counts towards a welcome bonus
capped at WELCOME_CAP. What is earned by running is capped at MONTHLY_CAP per calendar month (of the
activity's date; weekly Strava exports smooth out over the month). Spending: routes, levels and evolutions
of the familiers (app/game/pets.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..game.wallet import Wallet
from .store import ExploreStore

PER_KM_RUN = 1.0  # every km run (visible parts of timed activities, <= 25 km/h)
PER_KM_NEW = 2.0  # plus, for the paths run for the first time
PER_KM2_AREA = 10.0  # area discovered (50 m each side of the paths run)
MILESTONE_CREDITS = {10: 10, 25: 20, 50: 40, 75: 60, 90: 100}  # % of a commune's paths
BADGE_CREDITS = 25
POI_KIND_CREDITS = {"peak": 10, "waterfall": 10, "viewpoint": 5, "lake": 5}
POI_CATEGORY_CREDITS = {"heritage": 3, "nature": 2, "water": 2, "park": 1, "utility": 1}
RATING_CREDITS = 5  # an activity rated for the first time
RATINGS_PER_DAY = 10  # rewarded ratings a day
WELCOME_CAP = 500
ROUTE_PER_KM = 1  # cost of a generated route, per km
MONTHLY_CAP = 2000  # earned by running in a calendar month (spending does not give room back)
HISTORY_GRACE = timedelta(days=14)  # an activity of the last two weeks, imported late, still earns in full
RUNNING_KINDS = ("activity", "area", "poi", "milestone", "badge")  # what the monthly cap counts


def poi_credits(category: str, kind: str) -> int:
    return POI_KIND_CREDITS.get(kind, POI_CATEGORY_CREDITS.get(category, 1))


def activity_credits(run_m: float, new_m: float, area_m2: float) -> int:
    return round(run_m / 1000 * PER_KM_RUN + new_m / 1000 * PER_KM_NEW + area_m2 / 1e6 * PER_KM2_AREA)


def achievement_credits(a: dict) -> int:
    if a["kind"] == "milestone":
        return MILESTONE_CREDITS.get(int(a["id"].rsplit(":", 1)[1]), 0)
    return BADGE_CREDITS


def _parse(date: str | None) -> datetime | None:
    if not date:
        return None
    try:
        d = datetime.fromisoformat(date)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def sync(wallet: Wallet, store: ExploreStore, user: str, achievements: list[dict], now: datetime | None = None) -> int:
    """Credit what was earned and is not in the ledger yet. Returns the number of rows added."""
    now = now or datetime.now(timezone.utc)
    start, _ = wallet.start(user)
    first = start is None
    if first:
        wallet.set_start(user, now.isoformat())
        start = now.isoformat()
    cutoff = _parse(start) - HISTORY_GRACE
    known = wallet.keys(user)

    def old(date: str | None) -> bool:
        if first:
            return True
        d = _parse(date)
        return d is not None and d < cutoff

    entries = []
    unrecorded = False  # activities processed before their new area was recorded (all of them history)
    done = store.activities_done(user)
    for a in done:
        key = f"act:{a['activity']}"
        if key in known:
            continue
        unrecorded |= a["area_m2"] is None
        area = a["area_m2"] or 0.0
        amount = activity_credits(a["run_m"], a["new_m"], area)
        if amount > 0:
            entries.append({"key": key, "amount": amount, "kind": "activity", "label": "Sortie", "date": a["date"],
                            "detail": {"run_m": round(a["run_m"]), "new_m": round(a["new_m"]), "area_m2": round(area)},
                            "history": old(a["date"])})
    if first and unrecorded:  # their area, all at once
        area = store.totals(user)["area_m2"] - sum(a["area_m2"] or 0.0 for a in done)
        if area > 0:
            entries.append({"key": "history:area", "amount": round(area / 1e6 * PER_KM2_AREA), "kind": "area",
                            "label": "Superficie découverte", "date": None, "detail": {"area_m2": round(area)}, "history": True})
    for p in store.discovered(user):
        key = f"poi:{p['poi']}"
        if key not in known:
            entries.append({"key": key, "amount": poi_credits(p["category"], p["kind"]), "kind": "poi", "label": p["name"],
                            "date": p["first_date"], "detail": {"category": p["category"], "kind": p["kind"]},
                            "history": old(p["first_date"])})
    for a in achievements:
        key = f"ach:{a['id']}"
        if a["achieved"] and key not in known:
            entries.append({"key": key, "amount": achievement_credits(a), "kind": a["kind"], "label": a["title"],
                            "date": now.isoformat(), "history": first})
    _cap_monthly(wallet, user, entries, now)
    added = wallet.credit(user, entries)
    _top_up_welcome(wallet, user)
    return added


def _month(date: str | None, now: datetime) -> str:
    return (date or now.isoformat())[:7]


def _cap_monthly(wallet: Wallet, user: str, entries: list[dict], now: datetime) -> None:
    """Beyond MONTHLY_CAP earned in a month, a gain is recorded (never paid later) but reduced, down to 0."""
    used: dict[str, int] = {}
    for r in wallet.rows(user, history=False):
        if r["kind"] in RUNNING_KINDS:
            used[_month(r["date"], now)] = used.get(_month(r["date"], now), 0) + r["amount"]
    for e in sorted((e for e in entries if not e["history"]), key=lambda e: e.get("date") or ""):
        month = _month(e.get("date"), now)
        grant = max(0, min(e["amount"], MONTHLY_CAP - used.get(month, 0)))
        if grant < e["amount"]:
            e["detail"] = {**(e.get("detail") or {}), "capped_from": e["amount"]}
            e["amount"] = grant
        used[month] = used.get(month, 0) + grant


def _top_up_welcome(wallet: Wallet, user: str) -> None:
    """The welcome bonus: the history's worth, up to WELCOME_CAP (topped up when older activities come in)."""
    rows = wallet.rows(user)
    target = min(WELCOME_CAP, sum(r["amount"] for r in rows if r["history"]))
    given = sum(r["amount"] for r in rows if r["kind"] == "welcome")
    if target > given:
        wallet.credit(user, [{"key": f"welcome:{target}", "amount": target - given, "kind": "welcome",
                              "label": "Bonus de bienvenue", "date": datetime.now(timezone.utc).isoformat()}])


def reward_rating(wallet: Wallet, user: str, activity: str, now: datetime | None = None) -> int:
    """Points for rating an activity, the first time only, RATINGS_PER_DAY a day at most. Returns them."""
    now = now or datetime.now(timezone.utc)
    today = now.isoformat()[:10]
    if sum(1 for r in wallet.rows(user, history=False, limit=200) if r["kind"] == "rating" and (r["date"] or "")[:10] == today) >= RATINGS_PER_DAY:
        return 0
    added = wallet.credit(user, [{"key": f"rating:{activity}", "amount": RATING_CREDITS, "kind": "rating",
                                  "label": "Évaluation d'une sortie", "date": now.isoformat()}])
    return RATING_CREDITS if added else 0


def balance(wallet: Wallet, user: str) -> int:
    return wallet.balance(user)


def summary(wallet: Wallet, user: str, recent: int = 50, now: datetime | None = None) -> dict:
    """Balance, welcome bonus, earned this month (and its cap), the latest gains and spendings, and how much
    was earned since last announced."""
    now = now or datetime.now(timezone.utc)
    rows = wallet.rows(user)
    start, seen = wallet.start(user)
    history = sum(r["amount"] for r in rows if r["history"])
    earned = [r for r in rows if not r["history"]]
    by_kind: dict[str, int] = {}
    for r in earned:
        kind = "spend" if r["amount"] < 0 else r["kind"]
        by_kind[kind] = by_kind.get(kind, 0) + r["amount"]
    new = [r for r in earned if r["id"] > seen and r["amount"] > 0]
    month = now.isoformat()[:7]
    return {
        "started": start is not None,  # False: the first count is still to come
        "balance": wallet.balance(user),
        "welcome": sum(r["amount"] for r in rows if r["kind"] == "welcome"),
        "history": history,
        "welcome_cap": WELCOME_CAP,
        "month": {"earned": sum(r["amount"] for r in earned if r["kind"] in RUNNING_KINDS and _month(r["date"], now) == month),
                  "cap": MONTHLY_CAP},
        "by_kind": by_kind,
        "new": sum(r["amount"] for r in new),
        "entries": [{k: r[k] for k in ("key", "amount", "kind", "label", "date", "detail")} for r in earned[:recent]],
        "rates": {"route_km": ROUTE_PER_KM, "km_run": PER_KM_RUN, "km_new": PER_KM_NEW, "km2_area": PER_KM2_AREA, "badge": BADGE_CREDITS,
                  "milestones": MILESTONE_CREDITS, "rating": RATING_CREDITS},
    }


def adopt_legacy(wallet: Wallet, store: ExploreStore) -> int:
    """Once: the credits ledger kept in explore.sqlite before the game's wallet, moved into it. Returns rows moved."""
    if wallet.meta("legacy_credits") == "done":
        return 0
    n = 0
    for user, start, rows in store.legacy_credits():
        wallet.set_start(user, start)
        rows = sorted(rows, key=lambda r: r["id"])
        n += wallet.credit(user, [r for r in rows if r["kind"] != "spend"])  # gains and history
        _top_up_welcome(wallet, user)
        for r in rows:  # then the spendings (routes), through the balance
            if r["kind"] == "spend":
                n += bool(wallet.debit(user, -r["amount"], "route", r["key"], r["label"], r["detail"], up_to=True))
        wallet.mark_seen(user)
    wallet.set_meta("legacy_credits", "done")
    return n
