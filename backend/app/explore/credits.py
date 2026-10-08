"""Credits, earned by running: km run, new paths and area discovered, places visited, milestones and badges.

A ledger per account (table `credits`): one row per thing that earned credits, with a unique key, so that a
re-import or a re-processing never pays twice; the balance is the sum of the ledger. What was run before the
credits began (`history`: everything already there at the account's first sync, and later imports of
activities older than HISTORY_GRACE before that start) only counts towards a welcome bonus capped at
WELCOME_CAP. Spending comes later.
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
    return store.add_credits(user, entries)


def summary(store: ExploreStore, user: str, recent: int = 50) -> dict:
    """Balance, welcome bonus, what the latest gains were, and how much was earned since last announced."""
    rows = store.credits(user)
    _, seen = store.credits_start(user)
    history = sum(r["amount"] for r in rows if r["history"])
    welcome = min(WELCOME_CAP, history)
    earned = [r for r in rows if not r["history"]]
    by_kind: dict[str, int] = {}
    for r in earned:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["amount"]
    new = [r for r in earned if r["id"] > seen]
    return {
        "balance": welcome + sum(r["amount"] for r in earned),
        "welcome": welcome,
        "history": history,
        "welcome_cap": WELCOME_CAP,
        "by_kind": by_kind,
        "new": sum(r["amount"] for r in new),
        "entries": [{k: r[k] for k in ("key", "amount", "kind", "label", "date", "detail")} for r in earned[:recent]],
        "rates": {"km_run": PER_KM_RUN, "km_new": PER_KM_NEW, "km2_area": PER_KM2_AREA, "badge": BADGE_CREDITS,
                  "milestones": MILESTONE_CREDITS},
    }
