"""Canonical matching keys for Polarsteps step ↔ memory deduplication.

The import read path (`GET /api/polarsteps/trips/{id}/steps`) and the write path
(`POST /api/memories/`) must agree on *when* a step is "already imported".
Historically they didn't: the read path compared raw `(name, date)` while the
write path only knew `polarsteps_step_id`, so re-imports of memories created
before the step-id column existed produced duplicates. These helpers are the
single source of truth both paths share.
"""
from __future__ import annotations

from typing import Optional, Tuple


def normalize_name(name: Optional[str]) -> Optional[str]:
    """Canonical form of a memory/step name for matching.

    Trims surrounding whitespace (Polarsteps names often carry a trailing space,
    e.g. ``'Leguevin - Toulouse '``) and collapses the empty string to ``None``
    so a nameless step (``format_step`` yields ``""``) matches a stored memory
    with ``name IS NULL``. Case is preserved deliberately — folding it would risk
    merging genuinely distinct places.
    """
    if name is None:
        return None
    stripped = name.strip()
    return stripped or None


def step_key(name: Optional[str], date: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """The ``(normalized_name, date)`` tuple used to compare a step to a memory."""
    return (normalize_name(name), date)
