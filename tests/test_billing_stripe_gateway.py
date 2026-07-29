"""The Stripe gateway's own translation layer (issue #121).

These exist because the rest of the billing tests hand plain dicts straight to
:func:`subscription_update_from_event`, which skips
:mod:`src.billing.stripe_gateway` entirely. That gap hid a bug that broke every
payment route in production: ``StripeObject`` does **not** subclass ``dict``, so
``session.get("url")`` resolves to the SDK's GET helper and raises
``AttributeError``, and ``dict(event)`` raises ``KeyError: 0``.

So every case here drives the gateway with genuine ``StripeObject`` instances
rather than dicts. A dict would pass while the real SDK type fails, which is
exactly how the bug survived.
"""
from __future__ import annotations

import json
import time
import types

import pytest
from stripe import StripeObject

import src.billing.stripe_gateway as gw
from src.billing.gateway import GatewayError
from src.billing.plans import FREE, TIER_1, TIER_2, TIER_3, price_lookup_key
from src.billing.stripe_gateway import StripeGateway, _field


def _obj(**fields) -> StripeObject:
    """A real StripeObject — the type the SDK actually returns."""
    return StripeObject.construct_from(dict(fields), "sk_test_x")


@pytest.fixture(autouse=True)
def _price_env(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_TIER_1", "price_t1")
    monkeypatch.setenv("STRIPE_PRICE_TIER_2", "price_t2")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")


class TestFieldAccess:
    def test_stripe_objects_have_no_dict_get(self):
        """The trap itself: .get is the API helper, not the dict accessor."""
        with pytest.raises(AttributeError):
            _obj(url="https://x").get("url")

    def test_field_reads_present_and_missing(self):
        o = _obj(url="https://x", customer=None)
        assert _field(o, "url") == "https://x"
        assert _field(o, "customer") is None
        assert _field(o, "never_set") is None


class TestCheckoutSession:
    def _gateway(self, monkeypatch, session):
        created = {}

        class _Session:
            @staticmethod
            def create(**params):
                created.update(params)
                return session

        fake = types.SimpleNamespace(checkout=types.SimpleNamespace(Session=_Session))
        monkeypatch.setattr("src.billing.stripe_gateway._stripe", lambda: fake)
        return StripeGateway(), created

    def test_returns_url_and_customer_from_a_stripe_object(self, monkeypatch):
        session = _obj(url="https://checkout.stripe.com/c/pay/cs_test_1",
                       customer="cus_new")
        gateway, _ = self._gateway(monkeypatch, session)
        out = gateway.create_checkout_session(
            user_info_id=6, plan="tier_2", email="a@b.c", customer_id="",
            success_url="https://app/ok", cancel_url="https://app/no",
        )
        assert out["url"] == "https://checkout.stripe.com/c/pay/cs_test_1"
        assert out["customer_id"] == "cus_new"

    def test_keeps_the_existing_customer_when_the_session_omits_one(self, monkeypatch):
        gateway, params = self._gateway(monkeypatch, _obj(url="https://u", customer=None))
        out = gateway.create_checkout_session(
            user_info_id=6, plan="tier_2", email="a@b.c", customer_id="cus_old",
            success_url="https://app/ok", cancel_url="https://app/no",
        )
        assert out["customer_id"] == "cus_old"
        # An existing customer is reused rather than a second one created.
        assert params["customer"] == "cus_old"
        assert "customer_email" not in params

    def test_unconfigured_price_is_refused(self, monkeypatch):
        monkeypatch.delenv("STRIPE_PRICE_TIER_2", raising=False)
        gateway, _ = self._gateway(monkeypatch, _obj(url="https://u"))
        with pytest.raises(GatewayError):
            gateway.create_checkout_session(
                user_info_id=6, plan="tier_2", email="a@b.c", customer_id="",
                success_url="https://app/ok", cancel_url="https://app/no",
            )


class TestParseWebhook:
    def _gateway(self, monkeypatch, *, verified=True):
        def construct_event(payload, signature, secret):
            if not verified:
                raise ValueError("bad signature")
            return StripeObject.construct_from(json.loads(payload), "sk_test_x")

        fake = types.SimpleNamespace(
            Webhook=types.SimpleNamespace(construct_event=construct_event))
        monkeypatch.setattr("src.billing.stripe_gateway._stripe", lambda: fake)
        return StripeGateway()

    def test_returns_plain_nested_dicts(self, monkeypatch):
        """webhook_events walks the result with .get(), so every level must be a
        real dict — not the StripeObject the SDK hands back."""
        gateway = self._gateway(monkeypatch)
        payload = json.dumps({
            "id": "evt_1", "type": "customer.subscription.updated",
            "created": 1700000000,
            "data": {"object": {"id": "sub_1", "customer": "cus_1",
                                "status": "active",
                                "metadata": {"plan": "tier_2", "user_info_id": "6"}}},
        }).encode()

        event = gateway.parse_webhook(payload, "sig")

        assert type(event) is dict
        assert type(event["data"]) is dict
        assert type(event["data"]["object"]) is dict
        assert type(event["data"]["object"]["metadata"]) is dict
        # The access pattern webhook_events actually uses.
        assert event.get("type") == "customer.subscription.updated"
        obj = (event.get("data") or {}).get("object") or {}
        assert (obj.get("metadata") or {}).get("plan") == "tier_2"

    def test_bad_signature_raises(self, monkeypatch):
        gateway = self._gateway(monkeypatch, verified=False)
        with pytest.raises(GatewayError):
            gateway.parse_webhook(b"{}", "nope")

    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        gateway = self._gateway(monkeypatch)
        with pytest.raises(GatewayError):
            gateway.parse_webhook(b"{}", "sig")


class TestResolvePriceId:
    """Prices resolve by lookup key, not by an account-scoped id (issue #154)."""

    def _stripe(self, monkeypatch, *, prices=None, fail=False):
        """Fake SDK recording how many lookups were actually performed."""
        calls: list[list[str]] = []

        class _Price:
            @staticmethod
            def list(*, lookup_keys, limit):
                calls.append(list(lookup_keys))
                if fail:
                    raise RuntimeError("stripe unreachable")
                data = [_obj(id=prices[k]) for k in lookup_keys if k in (prices or {})]
                return _obj(data=data)

        monkeypatch.setattr("src.billing.stripe_gateway._stripe",
                            lambda: types.SimpleNamespace(Price=_Price))
        return calls

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch):
        for plan in ("TIER_1", "TIER_2", "TIER_3"):
            monkeypatch.delenv(f"STRIPE_PRICE_{plan}", raising=False)
        gw.reset_price_cache()
        yield
        gw.reset_price_cache()

    def test_a_pinned_env_var_wins_without_calling_stripe(self, monkeypatch):
        """The escape hatch, and what keeps the change non-breaking on rollout."""
        monkeypatch.setenv("STRIPE_PRICE_TIER_2", "price_pinned")
        calls = self._stripe(monkeypatch, prices={})
        assert gw.resolve_price_id(TIER_2) == "price_pinned"
        assert calls == []

    def test_resolves_by_lookup_key_when_unpinned(self, monkeypatch):
        key = price_lookup_key(TIER_2)
        calls = self._stripe(monkeypatch, prices={key: "price_resolved"})
        assert gw.resolve_price_id(TIER_2) == "price_resolved"
        assert calls == [[key]]

    def test_the_second_call_is_cached(self, monkeypatch):
        key = price_lookup_key(TIER_1)
        calls = self._stripe(monkeypatch, prices={key: "price_x"})
        assert gw.resolve_price_id(TIER_1) == "price_x"
        assert gw.resolve_price_id(TIER_1) == "price_x"
        assert len(calls) == 1

    def test_the_cache_expires_so_a_reprice_is_picked_up(self, monkeypatch):
        """A reprice transfers the lookup key onto a new price and archives the
        old one, so caching forever would keep selling something archived."""
        key = price_lookup_key(TIER_1)
        prices = {key: "price_old"}
        calls = self._stripe(monkeypatch, prices=prices)
        assert gw.resolve_price_id(TIER_1) == "price_old"

        prices[key] = "price_new"
        # Capture the real clock first: gw.time is the stdlib module, so the
        # replacement would otherwise call itself.
        later = time.time() + gw._CACHE_TTL_SECONDS + 1
        monkeypatch.setattr(gw.time, "time", lambda: later)
        assert gw.resolve_price_id(TIER_1) == "price_new"
        assert len(calls) == 2

    def test_a_missing_price_raises_and_is_cached_briefly(self, monkeypatch):
        calls = self._stripe(monkeypatch, prices={})
        with pytest.raises(GatewayError, match="lookup key"):
            gw.resolve_price_id(TIER_3)
        with pytest.raises(GatewayError):
            gw.resolve_price_id(TIER_3)
        assert len(calls) == 1, "a miss should be cached, not re-queried every time"

    def test_a_transport_failure_is_not_cached_as_missing(self, monkeypatch):
        """Otherwise a blip becomes a minute of refused checkouts."""
        calls = self._stripe(monkeypatch, fail=True)
        for _ in range(2):
            with pytest.raises(GatewayError):
                gw.resolve_price_id(TIER_2)
        assert len(calls) == 2

    def test_an_unsellable_plan_resolves_to_nothing(self, monkeypatch):
        calls = self._stripe(monkeypatch, prices={})
        assert gw.resolve_price_id(FREE) == ""
        assert calls == []
