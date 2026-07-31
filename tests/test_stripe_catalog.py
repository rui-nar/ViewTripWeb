"""The provisioner's customer-portal configuration (issue #153).

``POST /api/billing/change-plan`` opens a ``subscription_update_confirm`` portal
flow, and that flow is refused unless the account's portal configuration lists
the price being switched to. So this configuration is not cosmetic — it is the
other half of the endpoint, and the half that used to be a sequence of dashboard
clicks nobody could review.

The two rules asserted hardest are the ones a reader of `docs/BILLING.md` is
entitled to rely on: a downgrade lands at the end of the paid period, and so
does a cancellation.
"""
from __future__ import annotations

import types

import pytest

from scripts import stripe_catalog as cat
from src.billing import plans


@pytest.fixture
def price_ids() -> dict[str, str]:
    return {plan: f"price_{plan}" for plan in plans.PAID_PLANS}


class TestPortalFeatures:
    def test_every_paid_tier_is_switchable(self, price_ids):
        """A tier missing here is a tier the in-app switch cannot reach."""
        products = cat._portal_features(price_ids)["subscription_update"]["products"]
        assert [p["product"] for p in products] == [
            cat.product_id(plan) for plan in plans.PAID_PLANS
        ]
        assert [p["prices"] for p in products] == [
            [price_ids[plan]] for plan in plans.PAID_PLANS
        ]

    def test_price_updates_are_allowed(self, price_ids):
        update = cat._portal_features(price_ids)["subscription_update"]
        assert update["enabled"] is True
        assert "price" in update["default_allowed_updates"]

    def test_a_downgrade_is_scheduled_for_the_end_of_the_paid_period(self, price_ids):
        """The documented promise: they paid for that time, so they keep it —
        the same rule entitlements.plan_from_subscription applies to a
        cancellation."""
        update = cat._portal_features(price_ids)["subscription_update"]
        conditions = update["schedule_at_period_end"]["conditions"]
        assert {"type": "decreasing_item_amount"} in conditions

    def test_an_upgrade_is_immediate_and_prorated(self, price_ids):
        """Only a *decreasing* amount waits; anything else applies at once, and
        create_prorations is what charges the difference."""
        update = cat._portal_features(price_ids)["subscription_update"]
        assert update["proration_behavior"] == "create_prorations"
        types_ = {c["type"] for c in update["schedule_at_period_end"]["conditions"]}
        assert "shortening_interval" not in types_

    def test_cancelling_also_waits_for_the_period_to_end(self, price_ids):
        cancel = cat._portal_features(price_ids)["subscription_cancel"]
        assert cancel == {"enabled": True, "mode": "at_period_end"}

    def test_invoices_are_reachable(self, price_ids):
        """"Manage billing" is where a customer goes for their receipts."""
        assert cat._portal_features(price_ids)["invoice_history"]["enabled"] is True


class _FakeConfiguration:
    """Records writes; answers `list` from whatever it was seeded with."""

    def __init__(self, existing: list[dict] | None = None):
        self.existing = existing or []
        self.created: list[dict] = []
        self.modified: list[tuple[str, dict]] = []

    def list(self, *, limit):
        return {"data": self.existing}

    def create(self, **params):
        self.created.append(params)
        return {"id": "bpc_new"}

    def modify(self, config_id, **params):
        self.modified.append((config_id, params))
        return {"id": config_id}


def _stripe(configuration: _FakeConfiguration):
    return types.SimpleNamespace(
        billing_portal=types.SimpleNamespace(Configuration=configuration)
    )


class TestSyncPortalConfiguration:
    def test_a_dry_run_writes_nothing(self, price_ids):
        config = _FakeConfiguration()
        report = cat._sync_portal_configuration(
            _stripe(config), price_ids, apply=False)
        assert config.created == [] and config.modified == []
        assert any("CREATE" in line for line in report)

    def test_creates_one_when_the_account_has_none_of_ours(self, price_ids):
        config = _FakeConfiguration()
        cat._sync_portal_configuration(_stripe(config), price_ids, apply=True)
        assert len(config.created) == 1
        assert config.created[0]["metadata"]["managed_by"] == cat._MANAGED_BY

    def test_reuses_its_own_configuration_on_a_second_run(self, price_ids):
        """Stripe assigns the id, so without the marker every run would leave
        another configuration behind."""
        config = _FakeConfiguration(
            [{"id": "bpc_mine", "metadata": {"managed_by": cat._MANAGED_BY}}])
        cat._sync_portal_configuration(_stripe(config), price_ids, apply=True)
        assert config.created == []
        assert config.modified[0][0] == "bpc_mine"

    def test_leaves_a_hand_made_configuration_alone(self, price_ids):
        """Someone else's portal configuration is not ours to rewrite."""
        config = _FakeConfiguration([{"id": "bpc_theirs", "metadata": {}}])
        cat._sync_portal_configuration(_stripe(config), price_ids, apply=True)
        assert config.modified == []
        assert len(config.created) == 1

    def test_tolerates_a_configuration_with_no_metadata(self, price_ids):
        config = _FakeConfiguration([{"id": "bpc_old", "metadata": None}])
        cat._sync_portal_configuration(_stripe(config), price_ids, apply=True)
        assert len(config.created) == 1

    def test_skips_when_the_prices_do_not_exist_yet(self):
        """A dry run reports "(new)" for prices it did not create; naming those
        in a portal configuration would fail."""
        config = _FakeConfiguration()
        report = cat._sync_portal_configuration(
            _stripe(config), {plan: "(new)" for plan in plans.PAID_PLANS},
            apply=True)
        assert config.created == [] and config.modified == []
        assert any("SKIP" in line for line in report)
