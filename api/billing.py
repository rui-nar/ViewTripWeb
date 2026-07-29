"""Billing REST endpoints — plans, entitlements and Stripe checkout (issue #121).

Routes:
    GET  /api/billing/plans     — public plan catalogue (what the pricing UI renders)
    GET  /api/billing/me        — the caller's plan, limits and current usage
    POST /api/billing/checkout  — start a subscription purchase → provider URL
    POST /api/billing/portal    — open the provider's billing portal → URL
    POST /api/billing/webhook   — provider callbacks (signature-verified, no auth)

A deployment that has not configured a payment provider does not sell anything:
``/plans`` and ``/me`` still answer (reporting ``billing_enabled: false`` and no
limits) so the client can render "self-hosted, everything unlocked" without a
special case, and the three payment routes 404. That is the self-hosting
promise on the landing page, enforced in code.
"""
from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from models.db import get_session
from models.user import UserInfo
from src.billing import subscriptions as subs
from src.billing.entitlements import (
    billing_enabled,
    limits_for_user,
    plan_display_name,
    plan_for,
    project_count,
    quotas_enforced,
    storage_used,
    subscription_is_live,
)
from src.billing.gateway import GatewayError, get_gateway
from src.billing.plans import PAID_PLANS, catalogue
from src.billing.webhook_events import subscription_update_from_event
from src.utils.logging import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Where the provider sends the browser back to. Same var as the Strava OAuth
# callbacks and the invite links (api/strava.py, api/members.py).
_FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5500")


# ── Response schemas ──────────────────────────────────────────────────────────

class PlanOut(BaseModel):
    id: str = Field(description='Plan id — "free", "tier_1", "tier_2", "tier_3"')
    name: str
    price_label: str = Field(description="Human-readable price, e.g. '€5 / month'")
    limits: dict = Field(
        description="max_projects / max_storage_bytes / max_trip_days; "
                    "null = unlimited"
    )
    features: list[str]


class UsageOut(BaseModel):
    projects: int = Field(description="Trips the user owns")
    storage_bytes: int = Field(description="Bytes stored, as last accounted")


class BillingMeOut(BaseModel):
    billing_enabled: bool = Field(
        description="False on self-hosted instances — the client hides all "
                    "billing UI and never shows a paywall"
    )
    quotas_enforced: bool = Field(
        description="False while limits are measured but not enforced"
    )
    plan: str
    plan_name: str = Field(description="Display name of the plan in force")
    status: str = Field(description="Provider status, or 'none'")
    cancel_at_period_end: bool
    current_period_end: float = Field(description="Unix seconds; 0 when not subscribed")
    admin_override: bool = Field(description="Plan was granted by an operator")
    limits: dict
    usage: UsageOut


class CheckoutOut(BaseModel):
    url: str = Field(description="Provider-hosted page to redirect the browser to")


class WebhookAck(BaseModel):
    received: bool
    applied: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_gateway():
    gateway = get_gateway()
    if gateway is None:
        # 404, not 403: on a self-hosted instance this endpoint genuinely does
        # not exist, and saying so leaks nothing.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Billing is not enabled"
        )
    return gateway


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanOut], summary="List plans")
def list_plans():
    """Public plan catalogue — no authentication, so the landing page can use it."""
    return catalogue()


@router.get("/me", response_model=BillingMeOut, summary="Current plan and usage")
def billing_me(current_user: Annotated[dict, Depends(get_current_user)]):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = subs.get_subscription(sess, user_info_id)
        plan = plan_for(sess, user_info_id)
        limits = limits_for_user(sess, user_info_id)
        usage = UsageOut(
            projects=project_count(sess, user_info_id),
            storage_bytes=storage_used(sess, user_info_id),
        )
    return BillingMeOut(
        billing_enabled=billing_enabled(),
        quotas_enforced=quotas_enforced(),
        plan=plan,
        plan_name=plan_display_name(plan),
        status=(row.status if row else "none"),
        cancel_at_period_end=bool(row.cancel_at_period_end) if row else False,
        current_period_end=(row.current_period_end if row else 0.0),
        admin_override=bool(row.admin_override_plan) if row else False,
        limits=limits.as_dict(),
        usage=usage,
    )


class CheckoutBody(BaseModel):
    plan: Optional[str] = Field(
        default=None,
        description="Paid plan to buy — 'tier_1', 'tier_2' or 'tier_3'. "
                    "Defaults to the entry tier.",
    )
    return_path: Optional[str] = Field(
        default=None,
        description="Client route to come back to, e.g. '/settings'. Relative "
                    "paths only — anything else falls back to the default.",
    )


class PortalBody(BaseModel):
    return_path: Optional[str] = Field(
        default=None,
        description="Client route to come back to, e.g. '/settings'. Relative "
                    "paths only — anything else falls back to the default.",
    )


def _return_url(return_path: Optional[str], suffix: str) -> str:
    """Build an absolute return URL, refusing anything that isn't a local path.

    The path comes from the client and is handed to the payment provider as a
    redirect target, so an absolute URL here would be an open redirect.
    """
    path = return_path or "/settings"
    if not path.startswith("/") or path.startswith("//"):
        path = "/settings"
    return f"{_FRONTEND_ORIGIN}{path}{suffix}"


@router.post("/checkout", response_model=CheckoutOut, summary="Start a subscription")
def create_checkout(
    body: CheckoutBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    gateway = _require_gateway()
    user_info_id = int(current_user["sub"])
    # Default to the entry tier so a client that predates multiple plans (or an
    # upgrade prompt with nothing better to suggest) still buys something valid.
    plan = (body.plan or PAID_PLANS[0]).strip()
    if plan not in PAID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'{plan}' is not a plan that can be bought",
        )
    with get_session() as sess:
        user = sess.get(UserInfo, user_info_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        email = user.email
        row = subs.get_or_create(sess, user_info_id)
        customer_id = row.provider_customer_id
        # Checkout in subscription mode always creates a *new* subscription — it
        # never replaces one. Without this a subscriber tapping a different tier
        # in the plan picker ends up paying for two (issue #163). Changing tier
        # is the billing portal's job; see docs/BILLING.md.
        #
        # Only a live subscription blocks: one that is cancelled but still inside
        # its paid period is someone choosing their next plan, not double-buying,
        # and refusing them would mean waiting for the period to end.
        already_subscribed = subscription_is_live(row.status or "")

    if already_subscribed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active subscription — change your plan "
                   "from the billing portal.",
        )

    try:
        result = gateway.create_checkout_session(
            user_info_id=user_info_id,
            plan=plan,
            email=email,
            customer_id=customer_id,
            success_url=_return_url(body.return_path, "?checkout=success"),
            cancel_url=_return_url(body.return_path, "?checkout=cancelled"),
        )
    except GatewayError as exc:
        _log.warning("Checkout failed for user %s: %s", user_info_id, exc)
        raise HTTPException(status_code=502, detail="Could not start checkout")

    # Remember the customer id now: the user may abandon checkout, and next time
    # we want to reuse the same provider customer rather than create a second.
    new_customer = result.get("customer_id") or ""
    if new_customer and new_customer != customer_id:
        with get_session() as sess:
            row = subs.get_or_create(sess, user_info_id)
            row.provider_customer_id = new_customer
            sess.add(row)
            sess.commit()

    return CheckoutOut(url=result.get("url") or "")


@router.post("/portal", response_model=CheckoutOut, summary="Open the billing portal")
def create_portal(
    body: PortalBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    gateway = _require_gateway()
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = subs.get_subscription(sess, user_info_id)
        customer_id = row.provider_customer_id if row else ""
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No billing account yet — subscribe first",
        )
    try:
        result = gateway.create_portal_session(
            customer_id=customer_id,
            return_url=_return_url(body.return_path, ""),
        )
    except GatewayError as exc:
        _log.warning("Portal failed for user %s: %s", user_info_id, exc)
        raise HTTPException(status_code=502, detail="Could not open the billing portal")
    return CheckoutOut(url=result.get("url") or "")


@router.post("/webhook", response_model=WebhookAck, summary="Provider webhook")
async def webhook(request: Request):
    """Apply a provider event.

    Verification is on the raw body — re-serialising the JSON would change the
    bytes the signature was computed over. Anything we do not act on is still
    answered 2xx: a non-2xx makes the provider retry an event forever.
    """
    gateway = _require_gateway()
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = gateway.parse_webhook(payload, signature)
    except GatewayError as exc:
        _log.warning("Rejected webhook: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    update = subscription_update_from_event(event)
    if update is None:
        return WebhookAck(received=True, applied=False)

    with get_session() as sess:
        applied = subs.apply_update(sess, update)
    if applied:
        _log.info(
            "Billing: %s → plan=%s status=%s (event %s)",
            update.customer_id or update.user_info_id,
            update.plan, update.status, update.event_id,
        )
    return WebhookAck(received=True, applied=applied)
