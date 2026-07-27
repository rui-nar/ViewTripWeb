"""Registration now requires an email address and a first/last name (issue #110).

An account with no email can never be matched to a pending invite, and before
this change ``api/auth.py`` hardcoded ``email=""`` on every local account — so
the address had to become mandatory and had to actually be stored.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.auth import router as auth_router
from models.user import UserInfo
from src.admin.bootstrap import seed_admin
from src.email.address import is_valid_email, normalize_email


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


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


def _register(client, **overrides):
    payload = {
        "username": "alice@example.com",
        "password": "hunter2pass",
        "first_name": "Alice",
        "last_name": "Smith",
    }
    payload.update(overrides)
    return client.post("/api/auth/register", json=payload)


class TestEmailIsRequired:
    @pytest.mark.parametrize("bad", [
        "alice",              # no domain at all
        "alice@localhost",    # no dot in the domain
        "alice example.com",  # whitespace, no @
        "@example.com",       # empty local part
        "",
    ])
    def test_non_email_username_rejected(self, client, bad):
        assert _register(client, username=bad).status_code == 422

    def test_valid_email_accepted_and_stored(self, client, engine):
        assert _register(client).status_code == 201
        with Session(engine) as sess:
            ui = sess.exec(select(UserInfo)).first()
            assert ui.email == "alice@example.com"

    def test_email_is_normalized(self, client, engine):
        assert _register(client, username="  Alice@Example.COM  ").status_code == 201
        with Session(engine) as sess:
            ui = sess.exec(select(UserInfo)).first()
            # Stored lowercased/stripped, or a pending invite addressed to the
            # lowercase spelling would never match this account.
            assert ui.email == "alice@example.com"


class TestDisplayName:
    def test_composed_from_first_and_last(self, client):
        resp = _register(client)
        assert resp.json()["user"]["display_name"] == "Alice Smith"

    @pytest.mark.parametrize("field", ["first_name", "last_name"])
    def test_name_is_required(self, client, field):
        assert _register(client, **{field: ""}).status_code == 422
        assert _register(client, **{field: "   "}).status_code == 422

    def test_names_are_trimmed(self, client):
        resp = _register(client, first_name="  Alice  ", last_name=" Smith ")
        assert resp.json()["user"]["display_name"] == "Alice Smith"

    def test_missing_name_fields_rejected(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "bob@example.com", "password": "pw",
        })
        assert resp.status_code == 422


class TestExistingAccountsStillWork:
    def test_seeded_admin_can_still_log_in(self, engine, client):
        """The bootstrap admin is username "admin" with no email at all
        (src/admin/bootstrap.py). Enforcement belongs on registration only —
        validating at login would lock the operator out of their own server."""
        seed_admin()
        resp = client.post("/api/auth/token",
                           json={"username": "admin", "password": "admin"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == ""


class TestAddressHelpers:
    @pytest.mark.parametrize("value,expected", [
        ("a@b.co", True),
        ("first.last+tag@sub.example.com", True),
        ("  padded@example.com  ", True),
        ("no-at-sign", False),
        ("two@@example.com", False),
        ("no@dot", False),
    ])
    def test_is_valid_email(self, value, expected):
        assert is_valid_email(value) is expected

    def test_normalize_lowercases_and_strips(self):
        assert normalize_email("  Alice@Example.COM ") == "alice@example.com"
