"""How long a trip is, in days (issue #121).

A trip's length is its calendar span — first day to last day, inclusive —
**including days with nothing on them**. A three-week ride with a rest week in
the middle is 21 days, not 14: those empty days are still days of the trip, and
they show up as days in the app.

The span is derived rather than stored. ``trip_start``/``trip_end`` are optional
and frequently unset, so the bounds come from whichever of these is known:
the declared dates, and the dates of the activities, memories, journal entries
and transport segments the trip contains.

The arithmetic is pure and lives at the top; the one function that reads the
database is at the bottom and does nothing else.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Iterable

from sqlmodel import func, select

from models.project_db import (
    DBActivity,
    DBJournalEntry,
    DBMemory,
    DBProject,
    DBProjectItem,
)


def normalise(value) -> str | None:
    """Reduce a stored date to ``YYYY-MM-DD``, or None if it isn't one.

    Dates arrive in two shapes: memories, journals and segments store a plain
    date, activities an ISO datetime. Anything unparseable is dropped rather
    than guessed at — a bad row must not silently stretch someone's trip.
    """
    if not value:
        return None
    text = str(value)[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def bounds(values: Iterable) -> tuple[str | None, str | None]:
    """(earliest, latest) of the parseable dates, or (None, None) if there are none."""
    dates = sorted(d for d in (normalise(v) for v in values) if d)
    if not dates:
        return None, None
    return dates[0], dates[-1]


def span_days(first: str | None, last: str | None) -> int:
    """Inclusive day count between two dates. 0 when either end is unknown."""
    start, end = normalise(first), normalise(last)
    if start is None or end is None:
        return 0
    delta = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return max(delta, 0)


def span_of(values: Iterable) -> int:
    """Inclusive day count covering every date in ``values``."""
    return span_days(*bounds(values))


def project_day_bounds(sess, project_id: int) -> tuple[str | None, str | None]:
    """Earliest and latest date this trip touches, from every dated thing in it.

    Aggregated in SQL for the three big tables; segments are read as rows
    because their date lives inside a JSON blob, and a trip has a handful of
    them rather than thousands.
    """
    candidates: list = []

    project = sess.get(DBProject, project_id)
    if project is not None:
        candidates += [project.trip_start, project.trip_end]

    for model in (DBMemory, DBJournalEntry):
        first, last = sess.exec(
            select(func.min(model.date), func.max(model.date))
            .where(model.project_id == project_id)
        ).one()
        candidates += [first, last]

    # ISO datetimes sort lexicographically, so min/max on the string is right.
    first, last = sess.exec(
        select(func.min(DBActivity.start_date_local),
               func.max(DBActivity.start_date_local))
        .join(DBProjectItem, DBProjectItem.activity_id == DBActivity.id)
        .where(DBProjectItem.project_id == project_id)
    ).one()
    candidates += [first, last]

    segments = sess.exec(
        select(DBProjectItem.segment_json).where(
            DBProjectItem.project_id == project_id,
            DBProjectItem.item_type == "segment",
        )
    ).all()
    for raw in segments:
        try:
            candidates.append((json.loads(raw or "{}") or {}).get("date"))
        except (ValueError, TypeError):
            continue

    return bounds(candidates)
