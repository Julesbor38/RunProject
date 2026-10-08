"""Credits, earned by running: km run, new paths and area discovered, places visited, milestones and badges.

A ledger per account (table `credits`): one row per thing that earned credits, with a unique key, so that a
re-import or a re-processing never pays twice; the balance is the sum of the ledger. What was run before the
credits began (`history`: everything already there at the account's first sync, and later imports of
activities older than HISTORY_GRACE before that start) only counts towards a welcome bonus capped at
WELCOME_CAP. What is earned by running is capped at MONTHLY_CAP per calendar month (of the activity's date;
weekly Strava exports smooth out over the month). Spending: generating a route (`spend`, negative rows).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .store import ExploreStore

PER_KM_RUN = 1.0  # every km run (visible parts of timed activities, <= 25 km/h)
PER_KM_NEW = 2.0  # plus, for the paths run for the first time
PER_KM2_AREA = 10.0  # area discovered (50 m each side of the paths run)
MILESTONE_CREDITS = {10: 10, 25: 20, 50: 40, 75: 60, 90: 100}  # % of a commune's paths
BADGE_CREDITS = 25
POI_KIND_CREDITS = {"peak": 10, "waterfall": 10, "viewpoint": 5, "lake": 5}
POI_CATEGORY_CREDITS = {"heritage": 3, "nature": 2, "water": 2, "park": 1, "utility": 1}
WELCOME_CAP = 500
ROUTE_PER_KM = 1  # cost of a generated route, per km
MONTHLY_CAP = 2000  # earned by running in a calendar month (spending does not give room back)
HISTORY_GRACE = timedelta(days=14)  # an activity of the last two weeks, imported late, still earns in full


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


def sync(store: ExploreStore, user: str, achievements: list[dict], now: datetime | None = None) -> int:
    """Credit what was earned and is not in the ledger yet. Returns the number of rows added."""
    now = now or datetime.now(timezone.utc)
    start, _ = store.credits_start(user)
    first = start is None
    if first:
        store.set_credits_start(user, now.isoformat())
        start = now.isoformat()
    cutoff = _parse(start) - HISTORY_GRACE
    known = store.credit_keys(user)

    def old(date: str | None) -> bool:
        if first:
            return True
        d = _parse(date)
        return d is not None and d < cutoff

    entries = []
    unrecorded = False  # activities processed before their new area was recorded (all of them history)
    for a in store.activities_done(user):
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
        area = store.totals(user)["area_m2"] - sum(a["area_m2"] or 0.0 for a in store.activities_done(user))
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
    _cap_monthly(store, user, entries, now)
    return store.add_credits(user, entries)


def _month(date: str | None, now: datetime) -> str:
    return (date or now.isoformat())[:7]


def _cap_monthly(store: ExploreStore, user: str, entries: list[dict], now: datetime) -> None:
    """Beyond MONTHLY_CAP earned in a month, a gain is recorded (never paid later) but reduced, down to 0."""
    used: dict[str, int] = {}
    for r in store.credits(user, history=False):
        if r["kind"] != "spend":
            used[_month(r["date"], now)] = used.get(_month(r["date"], now), 0) + r["amount"]
    for e in sorted((e for e in entries if not e["history"]), key=lambda e: e.get("date") or ""):
        month = _month(e.get("date"), now)
        grant = max(0, min(e["amount"], MONTHLY_CAP - used.get(month, 0)))
        if grant < e["amount"]:
            e["detail"] = {**(e.get("detail") or {}), "capped_from": e["amount"]}
            e["amount"] = grant
        used[month] = used.get(month, 0) + grant


def balance(store: ExploreStore, user: str) -> int:
    rows = store.credits(user)
    return min(WELCOME_CAP, sum(r["amount"] for r in rows if r["history"])) + sum(r["amount"] for r in rows if not r["history"])


def spend(store: ExploreStore, user: str, key: str, amount: int, label: str, detail: dict | None = None) -> int:
    """Take `amount` credits (never below 0). Returns what was taken."""
    amount = max(0, min(amount, balance(store, user)))
    if amount:
        store.add_credits(user, [{"key": key, "amount": -amount, "kind": "spend", "label": label,
                                  "date": datetime.now(timezone.utc).isoformat(), "detail": detail}])
    return amount


def summary(store: ExploreStore, user: str, recent: int = 50, now: datetime | None = None) -> dict:
    """Balance, welcome bonus, earned this month (and its cap), the latest gains and spendings, and how much
    was earned since last announced."""
    now = now or datetime.now(timezone.utc)
    rows = store.credits(user)
    _, seen = store.credits_start(user)
    history = sum(r["amount"] for r in rows if r["history"])
    welcome = min(WELCOME_CAP, history)
    earned = [r for r in rows if not r["history"]]
    by_kind: dict[str, int] = {}
    for r in earned:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["amount"]
    new = [r for r in earned if r["id"] > seen and r["kind"] != "spend"]
    month = now.isoformat()[:7]
    return {
        "started": store.credits_start(user)[0] is not None,  # False: the first count is still to come
        "balance": welcome + sum(r["amount"] for r in earned),
        "welcome": welcome,
        "history": history,
        "welcome_cap": WELCOME_CAP,
        "month": {"earned": sum(r["amount"] for r in earned if r["kind"] != "spend" and _month(r["date"], now) == month),
                  "cap": MONTHLY_CAP},
        "by_kind": by_kind,
        "new": sum(r["amount"] for r in new),
        "entries": [{k: r[k] for k in ("key", "amount", "kind", "label", "date", "detail")} for r in earned[:recent]],
        "rates": {"route_km": ROUTE_PER_KM, "km_run": PER_KM_RUN, "km_new": PER_KM_NEW, "km2_area": PER_KM2_AREA, "badge": BADGE_CREDITS,
                  "milestones": MILESTONE_CREDITS},
    }
