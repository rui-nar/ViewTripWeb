"""Payment-gateway seam (issue #121).

Everything above this line is provider-agnostic; everything below it is Stripe.
The seam exists for two concrete reasons, not for speculative flexibility:

  * the API layer must be testable without network access or an SDK, and
  * ``import stripe`` must not happen at all on a self-hosted instance that
    never configured billing.

:func:`get_gateway` returns ``None`` when billing is off, which is the signal
the API uses to 404 the payment routes.
"""
from __future__ import annotations

from typing import Protocol


class GatewayError(Exception):
    """A call to the payment provider failed."""


class BillingGateway(Protocol):
    """The three provider operations the app needs."""

    def create_checkout_session(
        self, *, user_info_id: int, email: str, customer_id: str,
        success_url: str, cancel_url: str,
    ) -> dict:
        """Start a subscription purchase. Returns ``{"url", "customer_id"}``."""

    def create_portal_session(self, *, customer_id: str, return_url: str) -> dict:
        """Open the provider's billing portal. Returns ``{"url"}``."""

    def parse_webhook(self, payload: bytes, signature: str) -> dict:
        """Verify the signature and return the event dict. Raises on mismatch."""


_override: BillingGateway | None = None


def set_gateway(gateway: BillingGateway | None) -> None:
    """Install a gateway (tests inject a fake). ``None`` restores the default."""
    global _override
    _override = gateway


def get_gateway() -> BillingGateway | None:
    """The active gateway, or ``None`` when this deployment does not sell plans."""
    if _override is not None:
        return _override

    from src.billing.entitlements import billing_enabled

    if not billing_enabled():
        return None

    from src.billing.stripe_gateway import StripeGateway

    return StripeGateway()
