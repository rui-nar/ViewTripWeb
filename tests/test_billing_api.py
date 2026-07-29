"""Billing REST endpoints (issue #121).

Drives the real ``api.router.app`` so the routes, the 402 handler and the
dependency wiring are all exercised together. The payment provider is replaced
by a fake gateway — no network, no API key, no SDK behaviour to mock.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.billing as billing_mod
import models.db as db_module
from api.deps import get_current_user
from api.router import app
from models.billing import Subscription
from models.user import UserInfo
from src.billing.gateway import GatewayError, set_gateway
from src.billing.plans import FREE, PLAN_ORDER, TIER_1, TIER_2, TIER_3, TOP_PLAN


class FakeGateway:
    """Records what it was asked to do; returns plausible provider payloads."""

    def __init__(self, *, event=None, fail=False):
        self.event = event or {}
        self.fail = fail
        self.checkout_calls: list[dict] = []
        self.portal_calls: list[dict] = []
        self.webhook_calls: list[tuple[bytes, str]] = []

    def create_checkout_session(self, **kwargs):
        self.checkout_calls.append(kwargs)
        if self.fail:
            raise GatewayError("provider down")
        return {"url": "https://pay.test/session", "customer_id": "cus_new"}

    def create_portal_session(self, **kwargs):
        self.portal_calls.append(kwargs)
        if self.fail:
            raise GatewayError("provider down")
        return {"url": "https://pay.test/portal"}

    def parse_webhook(self, payload, signature):
        self.webhook_calls.append((payload, signature))
        if signature != "good":
            raise GatewayError("bad signature")
        return self.event


@pytest.fixture
def engine(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as sess:
        sess.add(UserInfo(id=1, email="a@example.com", display_name="A"))
        sess.commit()
    yield test_engine


@pytest.fixture
def client(engine, monkeypatch):
    for var in ("BILLING_ENABLED", "BILLING_ENFORCE_QUOTAS", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "email": "a@example.com"
    }
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        set_gateway(None)


@pytest.fixture
def gateway():
    gw = FakeGateway()
    set_gateway(gw)
    yield gw
    set_gateway(None)


def _subscription(engine, **kw) -> None:
    with Session(engine) as sess:
        sess.add(Subscription(user_info_id=1, **kw))
        sess.commit()


# ── Catalogue ─────────────────────────────────────────────────────────────────

class TestPlans:
    def test_lists_every_plan(self, client):
        res = client.get("/api/billing/plans")
        assert res.status_code == 200
        assert [p["id"] for p in res.json()] == list(PLAN_ORDER)

    def test_entries_carry_what_the_pricing_page_needs(self, client):
        entry = client.get("/api/billing/plans").json()[1]
        assert entry["name"] and entry["price_label"] and entry["features"]
        assert "max_trip_days" in entry["limits"]

    def test_is_public(self, engine):
        """The landing page renders pricing before anyone has logged in."""
        assert TestClient(app).get("/api/billing/plans").status_code == 200


# ── /me ───────────────────────────────────────────────────────────────────────

class TestBillingMe:
    def test_self_hosted_reports_no_billing_and_no_limits(self, client):
        body = client.get("/api/billing/me").json()
        assert body["billing_enabled"] is False
        assert body["plan"] == TOP_PLAN
        assert body["limits"]["max_projects"] is None
        assert body["limits"]["max_storage_bytes"] is None
        assert body["limits"]["max_trip_days"] is None

    def test_the_plan_carries_a_display_name(self, client, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        monkeypatch.setenv("FREE_NAME", "Starter")
        assert client.get("/api/billing/me").json()["plan_name"] == "Starter"

    def test_hosted_user_without_a_subscription_is_free(self, client, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        body = client.get("/api/billing/me").json()
        assert body["billing_enabled"] is True
        assert body["plan"] == FREE
        assert body["status"] == "none"
        assert body["limits"]["max_projects"] == 1

    def test_active_subscription_reports_cloud(self, client, engine, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        _subscription(engine, plan=TIER_2, status="active",
                      current_period_end=9e9, provider_customer_id="cus_1")
        body = client.get("/api/billing/me").json()
        assert body["plan"] == TIER_2
        assert body["status"] == "active"
        assert body["current_period_end"] == 9e9

    def test_admin_comp_is_reported(self, client, engine, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        _subscription(engine, admin_override_plan=TIER_2)
        body = client.get("/api/billing/me").json()
        assert body["plan"] == TIER_2
        assert body["admin_override"] is True

    def test_usage_is_reported(self, client, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        body = client.get("/api/billing/me").json()
        assert body["usage"] == {"projects": 0, "storage_bytes": 0}

    def test_requires_authentication(self, engine):
        assert TestClient(app).get("/api/billing/me").status_code == 401


# ── Checkout / portal ─────────────────────────────────────────────────────────

class TestCheckout:
    def test_404_when_the_deployment_sells_nothing(self, client):
        """A self-hoster must not find a paywall, not even a broken one."""
        assert client.post("/api/billing/checkout", json={}).status_code == 404

    def test_returns_the_provider_url(self, client, gateway):
        res = client.post("/api/billing/checkout", json={})
        assert res.status_code == 200
        assert res.json()["url"] == "https://pay.test/session"

    def test_passes_the_user_identity_to_the_provider(self, client, gateway):
        client.post("/api/billing/checkout", json={})
        call = gateway.checkout_calls[0]
        assert call["user_info_id"] == 1
        assert call["email"] == "a@example.com"

    def test_buys_the_tier_that_was_asked_for(self, client, gateway):
        client.post("/api/billing/checkout", json={"plan": TIER_3})
        assert gateway.checkout_calls[0]["plan"] == TIER_3

    def test_defaults_to_the_entry_tier(self, client, gateway):
        """An older client — or an upgrade prompt with nothing better to
        suggest — must still buy something valid."""
        client.post("/api/billing/checkout", json={})
        assert gateway.checkout_calls[0]["plan"] == TIER_1

    def test_the_free_plan_cannot_be_bought(self, client, gateway):
        res = client.post("/api/billing/checkout", json={"plan": FREE})
        assert res.status_code == 422
        assert gateway.checkout_calls == []

    def test_an_unknown_plan_is_refused(self, client, gateway):
        res = client.post("/api/billing/checkout", json={"plan": "tier_9"})
        assert res.status_code == 422
        assert gateway.checkout_calls == []

    def test_remembers_the_customer_id_for_next_time(self, client, engine, gateway):
        client.post("/api/billing/checkout", json={})
        with Session(engine) as sess:
            row = sess.get(Subscription, 1)
        assert row.provider_customer_id == "cus_new"

    def test_reuses_a_known_customer(self, client, engine, gateway):
        _subscription(engine, provider_customer_id="cus_existing")
        client.post("/api/billing/checkout", json={})
        assert gateway.checkout_calls[0]["customer_id"] == "cus_existing"

    def test_return_path_is_honoured(self, client, gateway, monkeypatch):
        monkeypatch.setattr(billing_mod, "_FRONTEND_ORIGIN", "https://app.test")
        client.post("/api/billing/checkout", json={"return_path": "/projects"})
        assert gateway.checkout_calls[0]["success_url"].startswith(
            "https://app.test/projects"
        )

    def test_absolute_return_url_is_refused(self, client, gateway, monkeypatch):
        """The return path is handed to the provider as a redirect target —
        accepting an absolute URL would make this an open redirect."""
        monkeypatch.setattr(billing_mod, "_FRONTEND_ORIGIN", "https://app.test")
        client.post("/api/billing/checkout",
                    json={"return_path": "https://evil.test/steal"})
        assert gateway.checkout_calls[0]["success_url"].startswith(
            "https://app.test/settings"
        )

    def test_protocol_relative_return_url_is_refused(self, client, gateway,
                                                     monkeypatch):
        monkeypatch.setattr(billing_mod, "_FRONTEND_ORIGIN", "https://app.test")
        client.post("/api/billing/checkout", json={"return_path": "//evil.test"})
        assert gateway.checkout_calls[0]["success_url"].startswith(
            "https://app.test/settings"
        )

    def test_provider_failure_is_a_502_not_a_500(self, client):
        set_gateway(FakeGateway(fail=True))
        assert client.post("/api/billing/checkout", json={}).status_code == 502


class TestPortal:
    def test_409_before_the_first_purchase(self, client, gateway):
        res = client.post("/api/billing/portal", json={})
        assert res.status_code == 409

    def test_returns_the_portal_url(self, client, engine, gateway):
        _subscription(engine, provider_customer_id="cus_1")
        res = client.post("/api/billing/portal", json={})
        assert res.json()["url"] == "https://pay.test/portal"
        assert gateway.portal_calls[0]["customer_id"] == "cus_1"

    def test_404_when_billing_is_disabled(self, client):
        assert client.post("/api/billing/portal", json={}).status_code == 404


# ── Webhook ───────────────────────────────────────────────────────────────────

def _checkout_event(user_info_id=1, plan=TIER_2):
    return {
        "id": "evt_1", "type": "checkout.session.completed", "created": 1000,
        "data": {"object": {
            "mode": "subscription", "customer": "cus_1", "subscription": "sub_1",
            "metadata": {"user_info_id": str(user_info_id), "plan": plan},
        }},
    }


class TestWebhook:
    def test_a_bad_signature_is_rejected(self, client):
        set_gateway(FakeGateway(event=_checkout_event()))
        res = client.post("/api/billing/webhook", content=b"{}",
                          headers={"stripe-signature": "forged"})
        assert res.status_code == 400

    def test_a_valid_event_upgrades_the_account(self, client, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        set_gateway(FakeGateway(event=_checkout_event()))
        res = client.post("/api/billing/webhook", content=b"{}",
                          headers={"stripe-signature": "good"})
        assert res.json() == {"received": True, "applied": True}
        assert client.get("/api/billing/me").json()["plan"] == TIER_2

    def test_verification_sees_the_raw_body(self, client):
        """Signatures are computed over the bytes; re-serialising would break them."""
        gw = FakeGateway(event=_checkout_event())
        set_gateway(gw)
        client.post("/api/billing/webhook", content=b'{"raw": 1}',
                    headers={"stripe-signature": "good"})
        assert gw.webhook_calls[0][0] == b'{"raw": 1}'

    def test_an_ignored_event_is_still_acknowledged(self, client):
        """A non-2xx makes the provider retry the event forever."""
        set_gateway(FakeGateway(event={
            "id": "evt_2", "type": "customer.created", "created": 1,
            "data": {"object": {}},
        }))
        res = client.post("/api/billing/webhook", content=b"{}",
                          headers={"stripe-signature": "good"})
        assert res.status_code == 200
        assert res.json() == {"received": True, "applied": False}

    def test_a_redelivered_event_is_applied_once(self, client, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        set_gateway(FakeGateway(event=_checkout_event()))
        headers = {"stripe-signature": "good"}
        first = client.post("/api/billing/webhook", content=b"{}", headers=headers)
        second = client.post("/api/billing/webhook", content=b"{}", headers=headers)
        assert first.json()["applied"] is True
        assert second.json()["applied"] is False

    def test_needs_no_authentication(self, client):
        """The provider calls this endpoint; it carries a signature, not a JWT."""
        app.dependency_overrides.clear()
        set_gateway(FakeGateway(event=_checkout_event()))
        res = client.post("/api/billing/webhook", content=b"{}",
                          headers={"stripe-signature": "good"})
        assert res.status_code == 200

    def test_404_when_billing_is_disabled(self, client):
        assert client.post("/api/billing/webhook", content=b"{}").status_code == 404
