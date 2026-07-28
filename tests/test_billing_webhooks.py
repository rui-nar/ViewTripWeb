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
from src.billing.plans import CLOUD, FREE
from src.billing.subscriptions import apply_update, get_subscription, set_admin_override
from src.billing.webhook_events import (
    SubscriptionUpdate,
    plan_for_price,
    subscription_update_from_event,
)


# ── Payload builders (shaped like real Stripe events) ─────────────────────────

def _subscription_event(etype: str, *, event_id="evt_1", created=1000,
                        status="active", period_end=5000, cancel=False,
                        customer="cus_1", sub_id="sub_1", price="price_cloud",
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
                    sub_id="sub_1", user_info_id=1, mode="subscription") -> dict:
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
            "metadata": {"user_info_id": str(user_info_id)},
        }},
    }


# ── Pure mapping ──────────────────────────────────────────────────────────────

class TestEventMapping:
    def test_checkout_completed_grants_cloud_and_carries_our_user_id(self):
        update = subscription_update_from_event(_checkout_event(user_info_id=42))
        assert update.plan == CLOUD
        assert update.status == "active"
        assert update.user_info_id == 42
        assert update.customer_id == "cus_1"
        assert update.subscription_id == "sub_1"

    def test_one_off_payment_is_not_a_subscription(self):
        """A ``payment`` mode session would grant a plan that never renews."""
        assert subscription_update_from_event(_checkout_event(mode="payment")) is None

    def test_subscription_updated_carries_status_and_period(self):
        update = subscription_update_from_event(
            _subscription_event("customer.subscription.updated",
                                status="active", period_end=7777)
        )
        assert update.plan == CLOUD
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
        event = _subscription_event("customer.subscription.updated")
        event["data"]["object"]["items"] = {"data": [{"plan": {"id": "plan_old"}}]}
        assert subscription_update_from_event(event).plan == CLOUD


class TestPlanForPrice:
    def test_any_price_grants_cloud(self):
        assert plan_for_price("price_whatever") == CLOUD

    def test_no_price_is_free(self):
        assert plan_for_price("") == FREE


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
        subscription_id="sub_1", plan=CLOUD, status="active",
        current_period_end=5000.0, cancel_at_period_end=False, user_info_id=1,
    )
    defaults.update(kw)
    return SubscriptionUpdate(**defaults)


class TestApplyUpdate:
    def test_creates_the_row_on_first_event(self, sess):
        assert apply_update(sess, _update()) is True
        row = get_subscription(sess, 1)
        assert row.plan == CLOUD
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
        assert get_subscription(sess, 1).plan == CLOUD

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
        set_admin_override(sess, 1, CLOUD)
        apply_update(sess, _update(plan=FREE, status="canceled"))
        row = get_subscription(sess, 1)
        assert row.admin_override_plan == CLOUD
        assert row.plan == FREE  # provider state is still recorded faithfully


class TestAdminOverride:
    def test_set_and_clear(self, sess):
        set_admin_override(sess, 1, CLOUD)
        assert get_subscription(sess, 1).admin_override_plan == CLOUD
        set_admin_override(sess, 1, "")
        assert get_subscription(sess, 1).admin_override_plan == ""

    def test_creates_a_row_for_a_user_who_never_paid(self, sess):
        assert get_subscription(sess, 1) is None
        set_admin_override(sess, 1, CLOUD)
        assert isinstance(get_subscription(sess, 1), Subscription)
