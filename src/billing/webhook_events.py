"""Pure translation of provider webhook events into subscription state (#121).

No SDK, no network, no database — a dict in, a :class:`SubscriptionUpdate` (or
``None``) out. That is what makes the interesting parts of billing testable:
every rule about which event grants what, and every defensive read of a payload
shape that Stripe has changed over the years, is exercised from a recorded JSON
fixture in the test suite.

Ordering and replay are the caller's job (see :mod:`api.billing`): Stripe
retries deliveries and does not guarantee order, so each update carries the
event id and timestamp needed to reject a duplicate or an out-of-date event.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.billing.plans import CLOUD, FREE

#: Events we act on. Anything else is acknowledged and ignored — Stripe sends a
#: lot of them, and a 2xx with no side effect is the correct response.
HANDLED_TYPES = frozenset({
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
})


@dataclass(frozen=True)
class SubscriptionUpdate:
    """The state one event implies. ``user_info_id`` is None when the event
    identifies the account only by provider customer id (most subscription
    events) — the caller then resolves it from the stored customer id."""

    event_id: str
    event_at: float
    customer_id: str
    subscription_id: str
    plan: str
    status: str
    current_period_end: float
    cancel_at_period_end: bool
    user_info_id: int | None = None


def plan_for_price(price_id: str) -> str:
    """Map a provider price id to a plan.

    Any priced line item maps to ``cloud``; only a subscription with no price at
    all maps to ``free``. There is exactly one paid plan, so matching on the
    configured price id would buy nothing and would break the day someone
    rotates the price in the dashboard — leaving a paying customer on the free
    tier, the worse of the two failure modes.
    """
    return CLOUD if price_id else FREE


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _period_end(sub: dict) -> float:
    """Read the period end, tolerating both Stripe payload generations.

    ``current_period_end`` sat on the subscription for years and moved onto the
    subscription *items* in the 2025 API versions. Read whichever is present so
    the integration survives an API-version bump.
    """
    top = _as_float(sub.get("current_period_end"))
    if top:
        return top
    items = (sub.get("items") or {}).get("data") or []
    return max((_as_float(i.get("current_period_end")) for i in items), default=0.0)


def _price_id(sub: dict) -> str:
    items = (sub.get("items") or {}).get("data") or []
    for item in items:
        price = item.get("price") or {}
        if price.get("id"):
            return str(price["id"])
        legacy_plan = item.get("plan") or {}
        if legacy_plan.get("id"):
            return str(legacy_plan["id"])
    return ""


def _customer_id(obj: dict) -> str:
    """Stripe sends ``customer`` as an id, or as an expanded object."""
    cust = obj.get("customer")
    if isinstance(cust, dict):
        return str(cust.get("id") or "")
    return str(cust or "")


def _subscription_id(obj: dict) -> str:
    sub = obj.get("subscription")
    if isinstance(sub, dict):
        return str(sub.get("id") or "")
    return str(sub or "")


def _user_info_id(obj: dict) -> int | None:
    """Our own user id, as attached when the checkout session was created."""
    meta = obj.get("metadata") or {}
    return _as_int(meta.get("user_info_id")) or _as_int(obj.get("client_reference_id"))


def subscription_update_from_event(event: dict) -> SubscriptionUpdate | None:
    """Translate one provider event. Returns ``None`` for events we ignore."""
    etype = event.get("type") or ""
    if etype not in HANDLED_TYPES:
        return None

    obj = ((event.get("data") or {}).get("object")) or {}
    event_id = str(event.get("id") or "")
    event_at = _as_float(event.get("created"))

    if etype == "checkout.session.completed":
        # A completed one-off payment is not a subscription — ignore it rather
        # than granting a plan that will never renew or cancel.
        if (obj.get("mode") or "subscription") != "subscription":
            return None
        return SubscriptionUpdate(
            event_id=event_id,
            event_at=event_at,
            customer_id=_customer_id(obj),
            subscription_id=_subscription_id(obj),
            plan=CLOUD,
            # The subscription object itself arrives in its own event moments
            # later with the authoritative status and period; "active" here just
            # unlocks the account immediately rather than making the user wait.
            status="active",
            current_period_end=0.0,
            cancel_at_period_end=False,
            user_info_id=_user_info_id(obj),
        )

    if etype == "invoice.payment_failed":
        # Do not downgrade here: Stripe moves the subscription to past_due /
        # unpaid and sends a subscription.updated event with the real state.
        # Acting on the invoice alone would cut access off mid-retry-window.
        return None

    if etype == "customer.subscription.deleted":
        return SubscriptionUpdate(
            event_id=event_id,
            event_at=event_at,
            customer_id=_customer_id(obj),
            subscription_id=str(obj.get("id") or ""),
            plan=FREE,
            status="canceled",
            current_period_end=_period_end(obj),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
            user_info_id=_user_info_id(obj),
        )

    # customer.subscription.created / updated
    return SubscriptionUpdate(
        event_id=event_id,
        event_at=event_at,
        customer_id=_customer_id(obj),
        subscription_id=str(obj.get("id") or ""),
        plan=plan_for_price(_price_id(obj)),
        status=str(obj.get("status") or ""),
        current_period_end=_period_end(obj),
        cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
        user_info_id=_user_info_id(obj),
    )
