"""Plan catalogue, limits and the pure entitlement rules (issue #121).

No database and no provider here — these are the rules that decide what a user
is allowed to do, exercised directly.
"""
from __future__ import annotations

import pytest

from src.billing import plans
from src.billing.entitlements import (
    billing_enabled,
    plan_from_subscription,
    quotas_enforced,
)
from src.billing.plans import CLOUD, FREE, limits_for, is_at_least, over_quota

_MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _clean_billing_env(monkeypatch):
    """Start every test from an unconfigured deployment."""
    for var in (
        "BILLING_ENABLED", "BILLING_ENFORCE_QUOTAS", "STRIPE_SECRET_KEY",
        "FREE_MAX_PROJECTS", "FREE_MAX_STORAGE_MB",
        "CLOUD_MAX_PROJECTS", "CLOUD_MAX_STORAGE_MB",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ── Limits ────────────────────────────────────────────────────────────────────

class TestLimits:
    def test_free_defaults(self):
        limits = limits_for(FREE)
        assert limits.max_projects == 1
        assert limits.max_storage_bytes == 500 * _MB

    def test_cloud_defaults(self):
        limits = limits_for(CLOUD)
        assert limits.max_projects is None       # unlimited trips
        assert limits.max_storage_bytes == 20 * 1024 * _MB

    def test_unknown_plan_falls_back_to_free(self):
        """Fail safe: an unrecognised plan must not hand out the paid limits."""
        assert limits_for("enterprise") == limits_for(FREE)

    def test_env_overrides_free(self, monkeypatch):
        monkeypatch.setenv("FREE_MAX_PROJECTS", "3")
        monkeypatch.setenv("FREE_MAX_STORAGE_MB", "2048")
        limits = limits_for(FREE)
        assert limits.max_projects == 3
        assert limits.max_storage_bytes == 2048 * _MB

    def test_env_can_make_a_limit_unlimited(self, monkeypatch):
        monkeypatch.setenv("FREE_MAX_STORAGE_MB", "unlimited")
        assert limits_for(FREE).max_storage_bytes is None

    def test_garbage_env_falls_back_to_the_default(self, monkeypatch):
        """A typo in an env var must not silently remove a limit."""
        monkeypatch.setenv("FREE_MAX_PROJECTS", "lots")
        assert limits_for(FREE).max_projects == 1

    def test_env_read_per_call_not_at_import(self, monkeypatch):
        assert limits_for(FREE).max_projects == 1
        monkeypatch.setenv("FREE_MAX_PROJECTS", "7")
        assert limits_for(FREE).max_projects == 7


class TestOverQuota:
    def test_under_the_limit(self):
        assert over_quota(used=10, incoming=5, limit=100) is False

    def test_exactly_on_the_limit_is_allowed(self):
        assert over_quota(used=95, incoming=5, limit=100) is False

    def test_one_byte_past_the_limit(self):
        assert over_quota(used=95, incoming=6, limit=100) is True

    def test_none_limit_is_never_exceeded(self):
        assert over_quota(used=10**12, incoming=10**12, limit=None) is False

    def test_already_over_the_limit_blocks_further_writes(self):
        assert over_quota(used=200, incoming=1, limit=100) is True


class TestPlanOrder:
    def test_cloud_satisfies_free(self):
        assert is_at_least(CLOUD, FREE) is True

    def test_free_does_not_satisfy_cloud(self):
        assert is_at_least(FREE, CLOUD) is False

    def test_unknown_plan_satisfies_nothing(self):
        assert is_at_least("enterprise", FREE) is False


# ── Provider state → plan ─────────────────────────────────────────────────────

class TestPlanFromSubscription:
    def test_active_grants_the_plan(self):
        assert plan_from_subscription(CLOUD, "active", 0, now=1000) == CLOUD

    def test_trialing_grants_the_plan(self):
        assert plan_from_subscription(CLOUD, "trialing", 0, now=1000) == CLOUD

    def test_past_due_still_grants_during_the_retry_window(self):
        """A failed renewal starts a provider retry window; locking the account
        out on day one loses customers who just need to update a card."""
        assert plan_from_subscription(CLOUD, "past_due", 0, now=1000) == CLOUD

    def test_cancelled_keeps_access_until_the_period_ends(self):
        assert plan_from_subscription(CLOUD, "canceled", 2000, now=1000) == CLOUD

    def test_cancelled_drops_to_free_after_the_period_ends(self):
        assert plan_from_subscription(CLOUD, "canceled", 2000, now=3000) == FREE

    def test_incomplete_checkout_grants_nothing(self):
        assert plan_from_subscription(CLOUD, "incomplete", 0, now=1000) == FREE

    def test_no_plan_is_free(self):
        assert plan_from_subscription("", "active", 0, now=1000) == FREE


# ── Deployment switches ───────────────────────────────────────────────────────

class TestBillingEnabled:
    def test_off_by_default(self):
        """The self-hosting promise: no configuration, no billing."""
        assert billing_enabled() is False

    def test_inferred_from_stripe_keys(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
        assert billing_enabled() is True

    def test_explicit_flag_wins_over_inference(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
        monkeypatch.setenv("BILLING_ENABLED", "false")
        assert billing_enabled() is False

    def test_explicit_on(self, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        assert billing_enabled() is True


class TestQuotasEnforced:
    def test_off_when_billing_is_off(self, monkeypatch):
        monkeypatch.setenv("BILLING_ENFORCE_QUOTAS", "1")
        assert quotas_enforced() is False

    def test_off_by_default_even_with_billing_on(self, monkeypatch):
        """Turning billing on measures usage; it does not start refusing writes
        for accounts that grew before the limits existed."""
        monkeypatch.setenv("BILLING_ENABLED", "1")
        assert quotas_enforced() is False

    def test_on_when_both_flags_are_set(self, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        monkeypatch.setenv("BILLING_ENFORCE_QUOTAS", "on")
        assert quotas_enforced() is True


class TestCatalogue:
    def test_lists_both_plans_with_their_limits(self, monkeypatch):
        monkeypatch.setenv("FREE_MAX_PROJECTS", "2")
        entries = plans.catalogue()
        assert [e["id"] for e in entries] == [FREE, CLOUD]
        assert entries[0]["limits"]["max_projects"] == 2

    def test_price_label_is_configurable(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PRICE_LABEL", "$5 / month")
        cloud = [e for e in plans.catalogue() if e["id"] == CLOUD][0]
        assert cloud["price_label"] == "$5 / month"
