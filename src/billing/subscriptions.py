"""Applying provider events to stored subscription state (issue #121).

Webhooks are at-least-once and unordered: Stripe retries a delivery it did not
get a 2xx for, and a ``checkout.session.completed`` can land after the
``customer.subscription.updated`` it logically precedes. Two guards make that
harmless — the same event id is never applied twice, and an event older than
the one already applied is dropped rather than overwriting newer state.
"""
from __future__ import annotations

import time

from sqlmodel import select

from models.billing import Subscription
from src.billing.webhook_events import SubscriptionUpdate
from src.utils.logging import get_logger

_log = get_logger(__name__)


def get_subscription(sess, user_info_id: int) -> Subscription | None:
    return sess.exec(
        select(Subscription).where(Subscription.user_info_id == user_info_id)
    ).first()


def get_or_create(sess, user_info_id: int) -> Subscription:
    row = get_subscription(sess, user_info_id)
    if row is None:
        row = Subscription(user_info_id=user_info_id)
        sess.add(row)
        sess.commit()
        sess.refresh(row)
    return row


def _by_customer(sess, customer_id: str) -> Subscription | None:
    if not customer_id:
        return None
    return sess.exec(
        select(Subscription).where(Subscription.provider_customer_id == customer_id)
    ).first()


def resolve_row(sess, update: SubscriptionUpdate) -> Subscription | None:
    """Find the subscription row an event belongs to.

    Prefers our own user id (carried in checkout metadata) and falls back to the
    provider customer id, which is all most subscription events contain.
    """
    if update.user_info_id:
        row = get_subscription(sess, update.user_info_id)
        if row is None:
            row = Subscription(user_info_id=update.user_info_id)
        return row
    return _by_customer(sess, update.customer_id)


def apply_update(sess, update: SubscriptionUpdate) -> bool:
    """Apply one event's state. Returns True when the row changed.

    Returns False — without an error — when the event is a duplicate, is older
    than what we already applied, or cannot be attributed to any account. All
    three are normal and must still be acknowledged with a 2xx, or Stripe will
    retry them forever.
    """
    row = resolve_row(sess, update)
    if row is None:
        _log.info(
            "Webhook %s: no account for customer %s — ignoring",
            update.event_id, update.customer_id,
        )
        return False

    if update.event_id and row.last_event_id == update.event_id:
        return False  # already applied (Stripe redelivery)
    if update.event_at and row.last_event_at and update.event_at < row.last_event_at:
        return False  # out-of-order redelivery of an older event

    row.plan = update.plan
    row.status = update.status
    row.provider = "stripe"
    if update.customer_id:
        row.provider_customer_id = update.customer_id
    if update.subscription_id:
        row.provider_subscription_id = update.subscription_id
    # A checkout-completed event carries no period; keep whatever the
    # subscription event gave us rather than zeroing the paid-until date.
    if update.current_period_end:
        row.current_period_end = update.current_period_end
    row.cancel_at_period_end = update.cancel_at_period_end
    row.last_event_id = update.event_id
    row.last_event_at = update.event_at
    row.updated_at = time.time()
    sess.add(row)
    sess.commit()
    return True


def set_admin_override(sess, user_info_id: int, plan: str) -> Subscription:
    """Grant or clear an operator-granted plan (``""`` clears it)."""
    row = get_or_create(sess, user_info_id)
    row.admin_override_plan = plan
    row.updated_at = time.time()
    sess.add(row)
    sess.commit()
    sess.refresh(row)
    return row
