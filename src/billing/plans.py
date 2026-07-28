"""Plan catalogue and per-plan limits (issue #121).

Pure data + pure functions: no DB, no network, no provider SDK. Everything a
caller needs to answer "what is this plan allowed to do" lives here, which keeps
the numbers testable and lets the client render the pricing table from the same
source the server enforces.

The limits are read from the environment at import time (same pattern as
``api/strava.py``) so the hosted deployment can retune them without a release.
``None`` means unlimited.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

FREE = "free"
CLOUD = "cloud"

#: Ordered weakest → strongest. Used to compare two plans without a lookup table.
PLAN_ORDER = (FREE, CLOUD)

_MB = 1024 * 1024


def _env_int(name: str, default: int | None) -> int | None:
    """Read an int from the environment; empty / "unlimited" / "-1" → ``None``."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("unlimited", "none", "-1"):
        return None
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Limits:
    """Per-plan ceilings. ``None`` = unlimited."""

    max_projects: int | None
    max_storage_bytes: int | None

    def as_dict(self) -> dict:
        return {
            "max_projects": self.max_projects,
            "max_storage_bytes": self.max_storage_bytes,
        }


def _free_limits() -> Limits:
    return Limits(
        max_projects=_env_int("FREE_MAX_PROJECTS", 1),
        max_storage_bytes=_mb_to_bytes(_env_int("FREE_MAX_STORAGE_MB", 500)),
    )


def _cloud_limits() -> Limits:
    return Limits(
        max_projects=_env_int("CLOUD_MAX_PROJECTS", None),
        max_storage_bytes=_mb_to_bytes(_env_int("CLOUD_MAX_STORAGE_MB", 20 * 1024)),
    )


def _mb_to_bytes(mb: int | None) -> int | None:
    return None if mb is None else mb * _MB


#: Unlimited everything — what a self-hosted deployment (billing disabled) gets.
UNLIMITED = Limits(max_projects=None, max_storage_bytes=None)


def limits_for(plan: str) -> Limits:
    """Limits for a plan id. An unknown plan falls back to ``free`` (fail safe)."""
    if plan == CLOUD:
        return _cloud_limits()
    return _free_limits()


def is_at_least(plan: str, required: str) -> bool:
    """True when ``plan`` is ``required`` or stronger."""
    try:
        return PLAN_ORDER.index(plan) >= PLAN_ORDER.index(required)
    except ValueError:
        return False


def over_quota(used: int, incoming: int, limit: int | None) -> bool:
    """Would ``used + incoming`` exceed ``limit``? ``None`` limit is never over.

    The comparison is strict-greater so a value landing exactly on the limit is
    allowed: a 500 MB plan accepts the upload that brings you to exactly 500 MB.
    """
    if limit is None:
        return False
    return used + incoming > limit


def catalogue() -> list[dict]:
    """Public plan catalogue — what the pricing UI renders.

    Prices are not hard-coded here: the amount shown comes from the provider
    configuration (``CLOUD_PRICE_LABEL``), so changing what you charge does not
    require a code change.
    """
    return [
        {
            "id": FREE,
            "name": "Free",
            "price_label": os.environ.get("FREE_PRICE_LABEL", "Free"),
            "limits": limits_for(FREE).as_dict(),
            "features": [
                "One trip",
                "Strava & Polarsteps import",
                "Memories, encounters, journal",
                "Share links",
            ],
        },
        {
            "id": CLOUD,
            "name": "Cloud",
            "price_label": os.environ.get("CLOUD_PRICE_LABEL", "€4 / month"),
            "limits": limits_for(CLOUD).as_dict(),
            "features": [
                "Unlimited trips",
                "20 GB of photos",
                "Daily backups",
                "Priority support",
            ],
        },
    ]
