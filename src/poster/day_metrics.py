"""Per-day statistics for poster memory cards (issue #14, Unit D).

Pure logic over an in-memory ``Project`` — no DB session, no API, no
rendering. Computes the metrics a single poster card anchored on one date
needs:

- ``distance_m`` / ``elevation_m`` / ``encounter_count`` are scoped to *that
  day only* (what happened on this date).
- ``counters`` / ``tag_pie`` are cumulative — their running total as of (and
  including) that date, since counters and tag totals are inherently
  running-total concepts.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.models.activity import Activity
from src.models.project import Project
from src.project.repo_core import _compute_counter_stats


def _activity_date(a: Activity) -> Optional[str]:
    """Return an activity's local date as 'YYYY-MM-DD', or None if unset.

    Mirrors the date-key extraction in ``_compute_stats``:
    ``start_date_local`` may be a datetime or an ISO string.
    """
    if a.start_date_local is None:
        return None
    try:
        return a.start_date_local.date().isoformat()  # datetime
    except AttributeError:
        return str(a.start_date_local)[:10]           # string fallback


def compute_day_metrics(project: Project, date: str) -> Dict[str, Any]:
    """Per-day stats for a poster memory card anchored on *date* (YYYY-MM-DD)."""
    # ── Day-only distance/elevation, across ALL activity types ──────────────
    distance_m = 0.0
    elevation_m = 0.0
    for a in project.activities:
        if _activity_date(a) == date:
            distance_m += a.distance or 0.0
            elevation_m += a.total_elevation_gain or 0.0

    # ── Encounters on this day ───────────────────────────────────────────────
    encounter_count = sum(
        1
        for item in project.items
        if item.item_type == "encounter"
        and item.encounter is not None
        and item.encounter.date == date
    )

    # ── Counters: cumulative value as of *date* ──────────────────────────────
    counters = []
    for ctr in _compute_counter_stats(project):
        value = ctr["start"]
        for point in ctr["series"]:  # series is sorted ascending by date
            if point["date"] <= date:
                value = point["value"]
            else:
                break
        counters.append({"name": ctr["name"], "value": value})

    # ── Tag pie: ride distance by day tag, cumulative through *date* ────────
    tag_pie: Dict[str, float] = {}
    for a in project.activities:
        if (a.type or "other").lower() != "ride":
            continue
        act_date = _activity_date(a)
        if act_date is None or act_date > date:
            continue
        meta = project.day_meta.get(act_date)
        for tag in (meta.tags if meta else []):
            tag_pie[tag] = tag_pie.get(tag, 0.0) + (a.distance or 0.0)

    return {
        "distance_m": distance_m,
        "elevation_m": elevation_m,
        "encounter_count": encounter_count,
        "counters": counters,
        "tag_pie": tag_pie,
    }
