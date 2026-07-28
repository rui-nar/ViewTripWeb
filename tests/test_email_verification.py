"""Email verification (issue #110).

Verification is what turns the self-declared address collected at registration
into evidence the user can read mail there. Without it anyone could register
with someone else's address and claim a pending invite meant for them.

The gate is soft: an unverified account is fully usable, it just cannot send
invite mail or be matched to a pending invite.
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
import src.auth.email_verification as verification_mod
from api.auth import router as auth_router
from models.user import EmailVerification, UserInfo
from src.utils.rate_limit import reset_rate_limits


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def engine(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)
    return test_engine


class _FakeMailer:
    """Records instead of sending. No test may reach a real relay."""

    def __init__(self) -> None:
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture
def mailer(monkeypatch):
    fake = _FakeMailer()
    monkeypatch.setattr(verification_mod, "get_email_service", lambda: fake)
    return fake


@pytest.fixture
def client(engine, mailer):
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


def _register(client, email="alice@example.com"):
    return client.post("/api/auth/register", json={
        "username": email, "password": "hunter2pass",
        "first_name": "Alice", "last_name": "Smith",
    })


def _token_row(engine, user_id=None):
    with Session(engine) as sess:
        stmt = select(EmailVerification)
        if user_id is not None:
            stmt = stmt.where(EmailVerification.user_info_id == user_id)
        return sess.exec(stmt).first()


class TestRegistrationIssuesToken:
    def test_token_row_created(self, client, engine):
        _register(client)
        assert _token_row(engine) is not None

    def test_verification_email_is_sent(self, client, mailer):
        _register(client)
        assert len(mailer.sent) == 1
        assert mailer.sent[0].to == "alice@example.com"

    def test_link_carries_the_token(self, client, engine, mailer):
        _register(client)
        row = _token_row(engine)
        assert row.token in mailer.sent[0].text_body

    def test_new_account_starts_unverified(self, client):
        assert _register(client).json()["user"]["email_verified"] is False

    def test_registration_survives_a_dead_relay(self, client, monkeypatch):
        """A broken relay must not fail a registration that otherwise
        succeeded — the send is queued, and failures are logged not raised."""
        async def _boom(message):
            raise RuntimeError("relay down")
        monkeypatch.setattr(
            verification_mod, "get_email_service",
            lambda: type("M", (), {"send": staticmethod(_boom)})())
        assert _register(client).status_code == 201


class TestVerify:
    def test_valid_token_verifies_the_account(self, client, engine):
        reg = _register(client)
        uid = int(reg.json()["user"]["id"])
        row = _token_row(engine, uid)

        assert client.post("/api/auth/verify-email",
                           json={"token": row.token}).status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, uid).email_verified is True

    def test_token_is_single_use(self, client, engine):
        _register(client)
        token = _token_row(engine).token
        client.post("/api/auth/verify-email", json={"token": token})
        assert client.post("/api/auth/verify-email",
                           json={"token": token}).status_code == 404

    def test_unknown_token_rejected(self, client):
        assert client.post("/api/auth/verify-email",
                           json={"token": "nope"}).status_code == 404

    def test_expired_token_rejected(self, client, engine):
        reg = _register(client)
        uid = int(reg.json()["user"]["id"])
        with Session(engine) as sess:
            row = sess.exec(select(EmailVerification)).first()
            row.expires_at = time.time() - 1
            sess.add(row)
            sess.commit()
            token = row.token

        assert client.post("/api/auth/verify-email",
                           json={"token": token}).status_code == 404
        with Session(engine) as sess:
            assert sess.get(UserInfo, uid).email_verified is False

    def test_token_for_a_changed_address_is_rejected(self, client, engine):
        """The token proves control of the address it was issued for. If the
        account's address changed since, that proof says nothing about the
        new one."""
        reg = _register(client)
        uid = int(reg.json()["user"]["id"])
        token = _token_row(engine, uid).token
        with Session(engine) as sess:
            user = sess.get(UserInfo, uid)
            user.email = "someone.else@example.com"
            sess.add(user)
            sess.commit()

        assert client.post("/api/auth/verify-email",
                           json={"token": token}).status_code == 404
        with Session(engine) as sess:
            assert sess.get(UserInfo, uid).email_verified is False

    def test_verifying_one_account_does_not_touch_another(self, client, engine):
        first = _register(client, "alice@example.com")
        second = _register(client, "bob@example.com")
        bob_id = int(second.json()["user"]["id"])
        alice_token = _token_row(engine, int(first.json()["user"]["id"])).token

        client.post("/api/auth/verify-email", json={"token": alice_token})
        with Session(engine) as sess:
            assert sess.get(UserInfo, bob_id).email_verified is False


class TestMeReflectsVerification:
    def test_me_is_fresh_after_verifying_without_relogin(self, client, engine):
        """Verifying does not mint a new JWT, so /me must read the flag from
        the database or it would keep reporting the stale claim."""
        reg = _register(client)
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/auth/me", headers=headers).json()["email_verified"] is False

        client.post("/api/auth/verify-email",
                    json={"token": _token_row(engine).token})
        assert client.get("/api/auth/me", headers=headers).json()["email_verified"] is True


class TestResend:
    def test_resend_replaces_the_previous_token(self, client, engine):
        reg = _register(client)
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        first = _token_row(engine).token

        assert client.post("/api/auth/resend-verification",
                           headers=headers).status_code == 200
        second = _token_row(engine).token
        assert second != first
        # The old link must stop working, or a leaked one stays valid.
        assert client.post("/api/auth/verify-email",
                           json={"token": first}).status_code == 404
        assert client.post("/api/auth/verify-email",
                           json={"token": second}).status_code == 200

    def test_resend_sends_another_email(self, client, mailer):
        reg = _register(client)
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        client.post("/api/auth/resend-verification", headers=headers)
        assert len(mailer.sent) == 2

    def test_resend_is_a_noop_once_verified(self, client, engine, mailer):
        reg = _register(client)
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        client.post("/api/auth/verify-email",
                    json={"token": _token_row(engine).token})

        assert client.post("/api/auth/resend-verification",
                           headers=headers).status_code == 200
        assert len(mailer.sent) == 1  # no second send

    def test_resend_requires_auth(self, client):
        assert client.post("/api/auth/resend-verification").status_code in (401, 403)

    def test_resend_is_rate_limited(self, client):
        reg = _register(client)
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        codes = [client.post("/api/auth/resend-verification", headers=headers)
                 .status_code for _ in range(12)]
        assert 429 in codes, "an unbounded resend is a free mail relay"
