"""Stripe implementation of :class:`~src.billing.gateway.BillingGateway` (#121).

The only module in the codebase that imports the Stripe SDK, and it does so
lazily so a self-hosted instance never touches it.

Kept deliberately thin: it creates sessions and verifies signatures, and does
not interpret anything. Interpretation lives in
:mod:`src.billing.webhook_events`, where it can be tested against recorded
payloads without a network or an API key.
"""
from __future__ import annotations

import json
import os

from src.billing.gateway import GatewayError
from src.billing.webhook_events import price_id_for_plan
from src.utils.logging import get_logger

_log = get_logger(__name__)


def _stripe():
    """Import and configure the SDK on first use."""
    import stripe  # imported lazily — see module docstring

    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise GatewayError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = secret
    return stripe


def _field(obj, name: str):
    """Read a field off a Stripe SDK object.

    ``StripeObject`` does not subclass ``dict``: its ``.get`` is the API's GET
    helper, so ``session.get("url")`` raises ``AttributeError`` rather than
    returning the URL. Subscripting is the supported access, and a missing key
    raises, hence the membership check.
    """
    return obj[name] if name in obj else None


def cloud_price_id(plan: str) -> str:
    """Price id for a paid plan, from the environment (``STRIPE_PRICE_TIER_1``…)."""
    return price_id_for_plan(plan)


def webhook_secret() -> str:
    """Signing secret for webhook verification, from the environment."""
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


class StripeGateway:
    """Checkout, Customer Portal and webhook verification via Stripe."""

    def create_checkout_session(
        self, *, user_info_id: int, plan: str, email: str, customer_id: str,
        success_url: str, cancel_url: str,
    ) -> dict:
        stripe = _stripe()
        price = cloud_price_id(plan)
        if not price:
            raise GatewayError(f"STRIPE_PRICE_{plan.upper()} is not configured")
        metadata = {"user_info_id": str(user_info_id), "plan": plan}
        params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            # Both, on purpose: metadata rides along to the subscription object,
            # client_reference_id shows up in the dashboard for support.
            "client_reference_id": str(user_info_id),
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "allow_promotion_codes": True,
        }
        # Reuse the customer across purchases so one person is one customer in
        # Stripe (and their portal shows their whole history).
        if customer_id:
            params["customer"] = customer_id
        elif email:
            params["customer_email"] = email
        try:
            session = stripe.checkout.Session.create(**params)
        except Exception as exc:  # SDK raises a family of StripeError subclasses
            _log.warning("Stripe checkout session failed: %s", exc)
            raise GatewayError(str(exc)) from exc
        return {
            "url": _field(session, "url") or "",
            "customer_id": str(_field(session, "customer") or customer_id or ""),
        }

    def create_portal_session(self, *, customer_id: str, return_url: str) -> dict:
        stripe = _stripe()
        if not customer_id:
            raise GatewayError("No billing account for this user")
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id, return_url=return_url
            )
        except Exception as exc:
            _log.warning("Stripe portal session failed: %s", exc)
            raise GatewayError(str(exc)) from exc
        return {"url": _field(session, "url") or ""}

    def parse_webhook(self, payload: bytes, signature: str) -> dict:
        stripe = _stripe()
        secret = webhook_secret()
        if not secret:
            raise GatewayError("STRIPE_WEBHOOK_SECRET is not configured")
        try:
            stripe.Webhook.construct_event(payload, signature, secret)
        except Exception as exc:
            # Covers both a bad signature and a malformed body. Either way the
            # request did not come from Stripe as far as we can tell.
            raise GatewayError(f"Invalid webhook signature: {exc}") from exc
        # Signature verified above; take the event from the raw bytes rather than
        # the SDK object. ``StripeObject`` is not a dict — ``dict(event)`` raises
        # — and its recursive conversion is private, while webhook_events wants
        # plain nested dicts it can ``.get()`` through.
        return json.loads(payload)
