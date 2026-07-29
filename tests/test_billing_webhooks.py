"""Provider webhook events → subscription state (issue #121).

Two layers, both without a network:

  * :func:`subscription_update_from_event` is pure — fed the payload shapes
    Stripe actually sends, including the 2025 change that moved
    ``current_period_end`` onto subscription items.
  * :func:`apply_update` is fed those results against a real (in-memory) DB, to
    pin down the at-least-once, out-of-order delivery guarantees.
"""
from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.billing import Subscription
from models.user import UserInfo
from src.billing.plans import FREE, TIER_1, TIER_2, TIER_3
from src.billing.subscriptions import apply_update, get_subscription, set_admin_override
from src.billing.webhook_events import (
    SubscriptionUpdate,
    plan_for_price,
    subscription_update_from_event,
)


@pytest.fixture(autouse=True)
def _configured_prices(monkeypatch):
    """One Stripe price per paid tier, as a configured deployment has."""
    monkeypatch.setenv("STRIPE_PRICE_TIER_1", "price_t1")
    monkeypatch.setenv("STRIPE_PRICE_TIER_2", "price_t2")
    monkeypatch.setenv("STRIPE_PRICE_TIER_3", "price_t3")
    yield


# ── Payload builders (shaped like real Stripe events) ─────────────────────────

def _subscription_event(etype: str, *, event_id="evt_1", created=1000,
                        status="active", period_end=5000, cancel=False,
                        customer="cus_1", sub_id="sub_1", price="price_t2",
                        user_info_id=None, items_period=False) -> dict:
    item: dict = {"price": {"id": price}}
    if items_period:
        # Stripe 2025 API versions carry the period on the item, not the sub.
        item["current_period_end"] = period_end
    obj = {
        "id": sub_id,
        "customer": customer,
        "status": status,
        "cancel_at_period_end": cancel,
        "items": {"data": [item]},
    }
    if not items_period:
        obj["current_period_end"] = period_end
    if user_info_id is not None:
        obj["metadata"] = {"user_info_id": str(user_info_id)}
    return {"id": event_id, "type": etype, "created": created,
            "data": {"object": obj}}


def _checkout_event(*, event_id="evt_co", created=900, customer="cus_1",
                    sub_id="sub_1", user_info_id=1, mode="subscription",
                    plan=TIER_2) -> dict:
    metadata = {"user_info_id": str(user_info_id)}
    if plan is not None:
        metadata["plan"] = plan
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "created": created,
        "data": {"object": {
            "id": "cs_1",
            "mode": mode,
            "customer": customer,
            "subscription": sub_id,
            "client_reference_id": str(user_info_id),
            "metadata": metadata,
        }},
    }


# ── Pure mapping ──────────────────────────────────────────────────────────────

class TestEventMapping:
    def test_checkout_completed_grants_the_tier_that_was_bought(self):
        update = subscription_update_from_event(_checkout_event(user_info_id=42))
        assert update.plan == TIER_2
        assert update.status == "active"
        assert update.user_info_id == 42
        assert update.customer_id == "cus_1"
        assert update.subscription_id == "sub_1"

    def test_checkout_without_a_recorded_tier_falls_back_to_the_entry_one(self):
        """A session created before tiers existed, or by an older client: the
        subscription event that follows carries the real price and corrects it."""
        update = subscription_update_from_event(_checkout_event(plan=None))
        assert update.plan == TIER_1

    def test_checkout_with_an_unknown_tier_falls_back_to_the_entry_one(self):
        update = subscription_update_from_event(_checkout_event(plan="tier_9"))
        assert update.plan == TIER_1

    def test_one_off_payment_is_not_a_subscription(self):
        """A ``payment`` mode session would grant a plan that never renews."""
        assert subscription_update_from_event(_checkout_event(mode="payment")) is None

    def test_subscription_updated_carries_status_and_period(self):
        update = subscription_update_from_event(
            _subscription_event("customer.subscription.updated",
                                status="active", period_end=7777)
        )
        assert update.plan == TIER_2
        assert update.status == "active"
        assert update.current_period_end == 7777

    def test_period_end_read_from_items_when_absent_on_the_subscription(self):
        """Stripe moved this field onto items; both shapes must work."""
        update = subscription_update_from_event(
            _subscription_event("customer.subscription.updated",
                                period_end=8888, items_period=True)
        )
        assert update.current_period_end == 8888

    def test_deleted_drops_to_free(self):
        update = subscription_update_from_event(
            _subscription_event("customer.subscription.deleted", status="canceled")
        )
        assert update.plan == FREE
        assert update.status == "canceled"

    def test_cancel_at_period_end_is_carried_through(self):
        update = subscription_update_from_event(
            _subscription_event("customer.subscription.updated", cancel=True)
        )
        assert update.cancel_at_period_end is True

    def test_payment_failed_changes_nothing(self):
        """The subscription event that follows carries the real state; acting on
        the invoice alone would cut access off mid-retry-window."""
        event = {"id": "evt_f", "type": "invoice.payment_failed", "created": 1,
                 "data": {"object": {"customer": "cus_1", "subscription": "sub_1"}}}
        assert subscription_update_from_event(event) is None

    def test_unhandled_event_type_is_ignored(self):
        event = {"id": "evt_x", "type": "customer.created", "created": 1,
                 "data": {"object": {"id": "cus_1"}}}
        assert subscription_update_from_event(event) is None

    def test_expanded_customer_object_is_accepted(self):
        event = _subscription_event("customer.subscription.updated")
        event["data"]["object"]["customer"] = {"id": "cus_expanded"}
        assert subscription_update_from_event(event).customer_id == "cus_expanded"

    def test_empty_payload_does_not_raise(self):
        assert subscription_update_from_event({}) is None

    def test_subscription_without_price_is_free(self):
        event = _subscription_event("customer.subscription.updated")
        event["data"]["object"]["items"] = {"data": []}
        assert subscription_update_from_event(event).plan == FREE

    def test_legacy_plan_id_counts_as_a_price(self):
        """Old payloads carry the price under "plan"; it is still a paid line
        item, so it must not read as free."""
        event = _subscription_event("customer.subscription.updated")
        event["data"]["object"]["items"] = {"data": [{"plan": {"id": "price_t2"}}]}
        assert subscription_update_from_event(event).plan == TIER_2


class TestPlanForPrice:
    def test_each_configured_price_maps_to_its_tier(self):
        assert plan_for_price("price_t1") == TIER_1
        assert plan_for_price("price_t2") == TIER_2
        assert plan_for_price("price_t3") == TIER_3

    def test_no_price_is_free(self):
        assert plan_for_price("") == FREE

    def test_an_unrecognised_price_grants_the_entry_tier(self):
        """They are paying for something, so free is wrong; the top tier would
        turn a config typo into an invisible revenue leak."""
        assert plan_for_price("price_rotated_last_week") == TIER_1

    def test_an_unconfigured_deployment_grants_the_entry_tier(self, monkeypatch):
        for tier in ("TIER_1", "TIER_2", "TIER_3"):
            monkeypatch.delenv(f"STRIPE_PRICE_{tier}", raising=False)
        assert plan_for_price("price_t2") == TIER_1


# ── Applying updates to stored state ──────────────────────────────────────────

@pytest.fixture
def sess():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UserInfo(id=1, email="a@example.com", display_name="A"))
        session.commit()
        yield session


def _update(**kw) -> SubscriptionUpdate:
    defaults = dict(
        event_id="evt_1", event_at=1000.0, customer_id="cus_1",
        subscription_id="sub_1", plan=TIER_2, status="active",
        current_period_end=5000.0, cancel_at_period_end=False, user_info_id=1,
    )
    defaults.update(kw)
    return SubscriptionUpdate(**defaults)


class TestApplyUpdate:
    def test_creates_the_row_on_first_event(self, sess):
        assert apply_update(sess, _update()) is True
        row = get_subscription(sess, 1)
        assert row.plan == TIER_2
        assert row.status == "active"
        assert row.provider_customer_id == "cus_1"

    def test_replaying_the_same_event_is_a_no_op(self, sess):
        apply_update(sess, _update())
        assert apply_update(sess, _update()) is False

    def test_an_older_event_cannot_undo_a_newer_one(self, sess):
        """Stripe redelivers out of order; a stale 'canceled' must not land on
        top of an already-applied renewal."""
        apply_update(sess, _update(event_id="evt_new", event_at=2000.0))
        applied = apply_update(sess, _update(
            event_id="evt_old", event_at=1000.0, plan=FREE, status="canceled",
        ))
        assert applied is False
        assert get_subscription(sess, 1).plan == TIER_2

    def test_a_newer_event_updates_the_row(self, sess):
        apply_update(sess, _update(event_id="evt_1", event_at=1000.0))
        apply_update(sess, _update(
            event_id="evt_2", event_at=2000.0, plan=FREE, status="canceled",
        ))
        assert get_subscription(sess, 1).plan == FREE

    def test_events_are_matched_by_customer_id_when_our_id_is_absent(self, sess):
        apply_update(sess, _update())  # checkout event carries user_info_id
        applied = apply_update(sess, _update(
            event_id="evt_2", event_at=2000.0, user_info_id=None,
            status="past_due",
        ))
        assert applied is True
        assert get_subscription(sess, 1).status == "past_due"

    def test_an_unattributable_event_is_ignored_not_an_error(self, sess):
        """A 2xx is still owed, or the provider retries forever."""
        assert apply_update(sess, _update(
            user_info_id=None, customer_id="cus_unknown"
        )) is False

    def test_checkout_without_a_period_keeps_the_known_period(self, sess):
        apply_update(sess, _update(event_id="evt_sub", event_at=1000.0,
                                   current_period_end=9999.0))
        apply_update(sess, _update(event_id="evt_co", event_at=1500.0,
                                   current_period_end=0.0))
        assert get_subscription(sess, 1).current_period_end == 9999.0

    def test_a_webhook_does_not_clear_an_admin_comp(self, sess):
        set_admin_override(sess, 1, TIER_2)
        apply_update(sess, _update(plan=FREE, status="canceled"))
        row = get_subscription(sess, 1)
        assert row.admin_override_plan == TIER_2
        assert row.plan == FREE  # provider state is still recorded faithfully


class TestAdminOverride:
    def test_set_and_clear(self, sess):
        set_admin_override(sess, 1, TIER_2)
        assert get_subscription(sess, 1).admin_override_plan == TIER_2
        set_admin_override(sess, 1, "")
        assert get_subscription(sess, 1).admin_override_plan == ""

    def test_creates_a_row_for_a_user_who_never_paid(self, sess):
        assert get_subscription(sess, 1) is None
        set_admin_override(sess, 1, TIER_2)
        assert isinstance(get_subscription(sess, 1), Subscription)
