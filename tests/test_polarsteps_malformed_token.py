"""A malformed remember_token should be rejected up front, not surfaced as a
generic connection failure.

PolarstepsClient silently falls back to user_id=0 when a token doesn't parse
as "{user_id}|{hash}" (see src/api/polarsteps_client.py), so a garbage token
used to make a real request to Polarsteps, which 404s on user 0 — surfacing
as a confusing "Could not reach Polarsteps: 404 ..." 502 instead of naming
the actual problem. /connect now detects this case before making any request
and returns a clear 401, distinct from the message a well-formed-but-rejected
(e.g. expired) token gets via the existing PermissionError path.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.polarsteps as ps_api
from api.deps import get_current_user
from api.polarsteps import _is_malformed_token, router as polarsteps_router


@pytest.fixture
def client():
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "a@e.com"}
    app.include_router(polarsteps_router)
    return TestClient(app)


# ── _is_malformed_token unit coverage ────────────────────────────────────────

@pytest.mark.parametrize("token", [
    "not-a-real-token",   # no "|" separator at all
    "0|somehash",         # parses to user_id 0 (the silent-fallback value)
    "-3|somehash",        # negative user_id can't be real
    "abc|somehash",       # non-numeric prefix
    "42|",                # empty hash half
])
def test_malformed_tokens_detected(token):
    assert _is_malformed_token(token) is True


@pytest.mark.parametrize("token", ["42|somehash", "1|abcdef0123456789"])
def test_well_formed_tokens_not_flagged(token):
    assert _is_malformed_token(token) is False


# ── /connect endpoint behaviour ──────────────────────────────────────────────

def test_malformed_token_rejected_before_any_request(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("PolarstepsClient should not be constructed for a malformed token")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _boom)

    resp = client.post("/api/polarsteps/connect", json={"remember_token": "garbage-token"})

    assert resp.status_code == 401
    assert "Invalid Polarsteps token" in resp.json()["detail"]


def test_well_formed_but_rejected_token_gets_existing_invalid_message(client, monkeypatch):
    class _FakeClient:
        def __init__(self, token):
            pass

        def get_me(self):
            raise PermissionError("Invalid or expired Polarsteps token")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    resp = client.post("/api/polarsteps/connect", json={"remember_token": "42|somehash"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Polarsteps token — please check and try again"


def test_malformed_and_well_formed_rejections_are_distinct(client, monkeypatch):
    """Both are clear 401s, but the wording differs — a malformed token names
    the format problem instead of reusing the "rejected by Polarsteps" text.
    """
    def _boom(*args, **kwargs):
        raise AssertionError("should not be called for a malformed token")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _boom)
    malformed_resp = client.post(
        "/api/polarsteps/connect", json={"remember_token": "garbage-token"}
    )

    class _FakeClient:
        def __init__(self, token):
            pass

        def get_me(self):
            raise PermissionError("Invalid or expired Polarsteps token")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)
    expired_resp = client.post(
        "/api/polarsteps/connect", json={"remember_token": "42|somehash"}
    )

    assert malformed_resp.status_code == 401
    assert expired_resp.status_code == 401
    assert malformed_resp.json()["detail"] != expired_resp.json()["detail"]


def test_malformed_token_never_reaches_generic_502_path(client, monkeypatch):
    """Regression guard for the original bug: a garbage token used to hit
    Polarsteps and 404, landing in the generic "Could not reach Polarsteps"
    502 branch. Make that branch raise if it's ever reached for this input.
    """
    class _UnreachableClient:
        def __init__(self, token):
            raise AssertionError("malformed token should be caught before construction")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _UnreachableClient)

    resp = client.post("/api/polarsteps/connect", json={"remember_token": "no-separator-here"})

    assert resp.status_code != 502
    assert "Could not reach Polarsteps" not in resp.json()["detail"]
