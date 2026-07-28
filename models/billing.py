"""Billing models — subscription state and per-user storage usage (issue #121).

Two tables, deliberately separate:

* ``Subscription`` mirrors what the payment provider says about a user. It is a
  *cache* of provider state, rewritten by webhooks; the provider remains the
  source of truth. ``admin_override_plan`` sits alongside it so a comped or
  support-granted plan survives untouched when a webhook rewrites the rest.
* ``UserUsage`` is a running counter of bytes on disk, incremented/decremented
  on upload and delete. Quota checks read this instead of walking the
  filesystem — ``src.admin.storage.dir_size`` takes seconds on a photo-heavy
  account, which is fine for a dashboard and far too slow for an upload path.
  A nightly job reconciles the counter against the real tree.
"""
from __future__ import annotations

import time

import sqlmodel


class Subscription(sqlmodel.SQLModel, table=True):
    """Per-user subscription state, as last reported by the payment provider."""

    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(
        foreign_key="userinfo.id", unique=True, index=True
    )
    # Plan this subscription grants while ``status`` is live: "free" | "cloud".
    plan: str = sqlmodel.Field(default="free")
    # Provider status verbatim ("active", "trialing", "past_due", "canceled", …);
    # "none" when the user has never checked out.
    status: str = sqlmodel.Field(default="none")
    provider: str = sqlmodel.Field(default="stripe")
    # Provider identifiers. The customer id is indexed because webhooks arrive
    # keyed by customer, not by our user id.
    provider_customer_id: str = sqlmodel.Field(default="", index=True)
    provider_subscription_id: str = sqlmodel.Field(default="")
    # End of the paid period, unix seconds. Access is granted up to this instant
    # even after a cancellation, which is what "cancel at period end" means.
    current_period_end: float = sqlmodel.Field(default=0.0)
    cancel_at_period_end: bool = sqlmodel.Field(default=False)
    # Operator-granted plan, independent of any payment ("" = no override).
    admin_override_plan: str = sqlmodel.Field(default="")
    # Last provider event applied, for idempotent webhook replay.
    last_event_id: str = sqlmodel.Field(default="")
    # Provider timestamp of the last applied event, so a redelivered *older*
    # event cannot move state backwards (webhooks arrive out of order).
    last_event_at: float = sqlmodel.Field(default=0.0)
    updated_at: float = sqlmodel.Field(default_factory=time.time)


class UserUsage(sqlmodel.SQLModel, table=True):
    """Running total of bytes stored under ``data/users/{id}/`` for one user."""

    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(
        foreign_key="userinfo.id", unique=True, index=True
    )
    storage_bytes: int = sqlmodel.Field(default=0)
    # When the counter was last reconciled against the real filesystem tree.
    reconciled_at: float = sqlmodel.Field(default=0.0)
    updated_at: float = sqlmodel.Field(default_factory=time.time)
