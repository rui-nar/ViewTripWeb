#!/usr/bin/env python
"""Provision the Stripe product/price catalogue for the paid tiers (issue #121).

The dashboard can do this in a few clicks, which is exactly the problem: those
clicks are unrecorded, unrepeatable, and have to be performed twice — once in
test mode and once in live. The three `price_...` ids they produce are what
`STRIPE_PRICE_TIER_1..3` point at, and a wrong one silently grants Tier 1
(see docs/BILLING.md). So the catalogue is declared here and applied by running
this, against either mode, as many times as you like.

**Names and descriptions are not written here.** They come from
`src.billing.plans`, the same module the server enforces and the pricing UI
renders, so a Stripe product can never advertise limits the server does not
grant. Only the amounts live in this file — Stripe is the one place that has to
know what to charge.

Idempotency has two handles:

* **Products** use a caller-supplied id (`traxjourney_tier_1`), so re-running
  updates the existing product rather than creating a second one.
* **Prices** use a `lookup_key`. A price's amount, currency and interval are
  **immutable** in Stripe — repricing is not an edit. So when an amount changes
  this creates a *new* price, moves the lookup key onto it
  (`transfer_lookup_key`), and archives the old one. Subscriptions already on
  the old price keep paying the old amount; Stripe does not re-price anyone
  behind your back, and neither does this script.

Dry run by default — it prints what it would do and touches nothing. Pass
``--apply`` to write, and additionally ``--live`` if the key is a live one:
building a live catalogue from guessed numbers leaves archived prices you can
never delete.

    export STRIPE_SECRET_KEY=sk_test_...
    python scripts/stripe_catalog.py                # show the plan
    python scripts/stripe_catalog.py --apply        # create/update
    python scripts/stripe_catalog.py --apply --live # against sk_live_...

On success it prints the `STRIPE_PRICE_TIER_*` block to copy into the
environment.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Run from anywhere: the catalogue is derived from src.billing.plans.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.billing import plans  # noqa: E402

#: Single currency for now. The lookup key encodes it so a second currency can
#: be added later without colliding with these.
CURRENCY = "eur"
INTERVAL = "month"

#: What to charge, in the smallest currency unit (99 = €0.99). The only numbers
#: in the catalogue that plans.py does not already own.
AMOUNTS_CENTS = {
    plans.TIER_1: 99,
    plans.TIER_2: 399,
    plans.TIER_3: 999,
}


def product_id(plan: str) -> str:
    return f"traxjourney_{plan}"


def lookup_key(plan: str) -> str:
    return f"traxjourney_{plan}_monthly_{CURRENCY}"


def env_var(plan: str) -> str:
    """The environment variable the server reads this price id from."""
    return f"STRIPE_PRICE_{plan.upper()}"


def description_for(plan: str) -> str:
    """Product blurb, generated from the plan limits so it cannot drift."""
    return " · ".join(plans.features_for(plan))


def _stripe(secret: str):
    import stripe

    stripe.api_key = secret
    return stripe


def _sync_product(stripe, plan: str, *, apply: bool) -> list[str]:
    """Create or update the product for ``plan``. Returns lines to report."""
    pid, name, blurb = product_id(plan), plans.plan_name(plan), description_for(plan)
    try:
        existing = stripe.Product.retrieve(pid)
    except stripe.error.InvalidRequestError:
        existing = None

    if existing is None:
        if apply:
            stripe.Product.create(
                id=pid, name=name, description=blurb,
                metadata={"plan": plan, "managed_by": "scripts/stripe_catalog.py"},
            )
        return [f"  product {pid}: CREATE  {name!r}"]

    # Index rather than .get(): Stripe's objects expose resource methods as
    # attributes, so `.get` is the API's GET helper, not the dict accessor.
    if existing["name"] == name and existing["description"] == blurb:
        return [f"  product {pid}: ok"]
    if apply:
        stripe.Product.modify(pid, name=name, description=blurb)
    return [f"  product {pid}: UPDATE name/description"]


def _sync_price(stripe, plan: str, *, apply: bool) -> tuple[str, list[str]]:
    """Ensure a price with the right amount exists. Returns (price_id, report)."""
    key, amount = lookup_key(plan), AMOUNTS_CENTS[plan]
    found = stripe.Price.list(lookup_keys=[key], limit=1)["data"] or []
    current = found[0] if found else None

    if current is not None:
        # A one-off price carrying this lookup key has recurring=None; treat it
        # as a mismatch rather than crashing, so the replace path fixes it.
        recurring = current["recurring"]
        matches = (
            current["unit_amount"] == amount
            and current["currency"] == CURRENCY
            and recurring is not None
            and recurring["interval"] == INTERVAL
        )
        if matches:
            return current["id"], [f"  price   {key}: ok  ({amount / 100:.2f} {CURRENCY.upper()})"]
        # Immutable — reprice by replacing, and carry the lookup key across so
        # nothing else has to be repointed.
        was = current["unit_amount"]
        if not apply:
            return "(new)", [
                f"  price   {key}: REPLACE {was / 100:.2f} → {amount / 100:.2f} "
                f"{CURRENCY.upper()} (archives {current['id']})"
            ]
        new = stripe.Price.create(
            product=product_id(plan), unit_amount=amount, currency=CURRENCY,
            recurring={"interval": INTERVAL}, lookup_key=key,
            transfer_lookup_key=True, nickname=f"{plans.plan_name(plan)} monthly ({CURRENCY.upper()})",
            metadata={"plan": plan},
        )
        stripe.Price.modify(current["id"], active=False)
        stripe.Product.modify(product_id(plan), default_price=new["id"])
        return new["id"], [
            f"  price   {key}: REPLACED {was / 100:.2f} → {amount / 100:.2f} "
            f"{CURRENCY.upper()}; archived {current['id']}"
        ]

    if not apply:
        return "(new)", [f"  price   {key}: CREATE  {amount / 100:.2f} {CURRENCY.upper()}/{INTERVAL}"]
    new = stripe.Price.create(
        product=product_id(plan), unit_amount=amount, currency=CURRENCY,
        recurring={"interval": INTERVAL}, lookup_key=key,
        nickname=f"{plans.plan_name(plan)} monthly ({CURRENCY.upper()})",
        metadata={"plan": plan},
    )
    stripe.Product.modify(product_id(plan), default_price=new["id"])
    return new["id"], [f"  price   {key}: CREATED {new['id']}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="perform the writes (default: dry run)")
    parser.add_argument("--live", action="store_true",
                        help="permit a live-mode key; required with sk_live_")
    args = parser.parse_args(argv)

    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        print("STRIPE_SECRET_KEY is not set", file=sys.stderr)
        return 2

    is_live = secret.startswith("sk_live_")
    if is_live and not args.live:
        print("refusing: STRIPE_SECRET_KEY is a live key; pass --live to confirm",
              file=sys.stderr)
        return 2

    stripe = _stripe(secret)
    mode = "LIVE" if is_live else "test"
    print(f"Stripe catalogue — {mode} mode — {'applying' if args.apply else 'dry run'}\n")

    price_ids: dict[str, str] = {}
    for plan in plans.PAID_PLANS:
        print(f"{plan} ({plans.plan_name(plan)})")
        for line in _sync_product(stripe, plan, apply=args.apply):
            print(line)
        pid, report = _sync_price(stripe, plan, apply=args.apply)
        for line in report:
            print(line)
        price_ids[plan] = pid
        print()

    print("Environment:")
    for plan in plans.PAID_PLANS:
        print(f"{env_var(plan)}={price_ids[plan]}")
    if not args.apply:
        print("\n(dry run — nothing was written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
