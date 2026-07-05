"""Upstream Strava failures must surface as meaningful HTTP status codes.

Regression: the Strava endpoints have no try/except around the client calls, so
an APIError raised by the client (e.g. Strava returning 403 "Application Status
Inactive") propagated as an unhandled exception → a bare 500 with no actionable
message. App-level exception handlers in api.router now map:

  * APIError            → 502 (upstream third-party failure)
  * AuthenticationError → 401 (client should re-authenticate)

This test drives the real `app` (with its registered handlers) to prove the
wiring, not just the handler functions in isolation.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.strava as strava_module
import models.db as db_module
from api.deps import get_current_user
from api.router import app
from models.user import StravaToken, UserInfo
from src.exceptions.errors import APIError, AuthenticationError


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        sess.add(
            StravaToken(
                user_info_id=u.id,
                access_token="tok",
                refresh_token="ref",
                expires_at=time.time() + 3600,
            )
        )
        sess.commit()
        uid = u.id

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_upstream_api_error_maps_to_502(client, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise APIError('Strava API error 403: {"message":"Forbidden"}')

    monkeypatch.setattr(strava_module, "_fetch_all_strava", _boom)
    # Bypass Strava client construction (CI has no client_id/secret) so the test
    # exercises only the app-level error-handler wiring, not real Strava config.
    monkeypatch.setattr(strava_module, "_strava_client_for_token",
                        lambda *_a, **_k: object())

    # start_date forces the date-API path, which fetches from Strava directly.
    resp = client.get("/api/strava/activities?start_date=2026-01-01")

    assert resp.status_code == 502
    assert "Strava" in resp.json()["detail"]


def test_upstream_auth_error_maps_to_401(client, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AuthenticationError("Strava access token is invalid or expired. Please re-authenticate")

    monkeypatch.setattr(strava_module, "_fetch_all_strava", _boom)
    monkeypatch.setattr(strava_module, "_strava_client_for_token",
                        lambda *_a, **_k: object())

    resp = client.get("/api/strava/activities?start_date=2026-01-01")

    assert resp.status_code == 401
    assert "re-authenticate" in resp.json()["detail"]
