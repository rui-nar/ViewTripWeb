"""Tests for the /api/auth/google login endpoint.

Focus: verification is resilient to small host clock drift (Google mints tokens
against its own clock, so a server lagging by a second must not reject fresh
tokens), and failure reasons are exposed only on dev builds.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient


def _client() -> TestClient:
    import api.router as router
    return TestClient(router.app)


def test_google_login_forwards_clock_skew_tolerance():
    """The Google verification must allow a non-zero clock-skew window so a
    server whose clock lags slightly does not reject freshly minted tokens."""
    import api.auth as auth

    with patch.object(
        auth, "verify_oauth2_token",
        side_effect=ValueError("Token used too early, 1 < 2."),
    ) as mock_verify, patch.object(auth, "_google_client_id", "client-123"):
        resp = _client().post("/api/auth/google", json={"id_token": "x"})

    assert resp.status_code == 401
    assert auth._GOOGLE_CLOCK_SKEW_SECONDS > 0
    _, kwargs = mock_verify.call_args
    assert kwargs.get("clock_skew_in_seconds") == auth._GOOGLE_CLOCK_SKEW_SECONDS


def test_google_login_keeps_response_generic_and_logs_reason(caplog):
    """The client only ever sees a generic 401; the real reason is logged
    server-side (never leaked in the response body)."""
    import logging

    import api.auth as auth

    with patch.object(
        auth, "verify_oauth2_token", side_effect=ValueError("boom-reason"),
    ), patch.object(auth, "_google_client_id", "client-123"), \
            caplog.at_level(logging.WARNING, logger="api.auth"):
        resp = _client().post("/api/auth/google", json={"id_token": "x"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Google id_token"
    assert "boom-reason" not in resp.json()["detail"]
    assert "boom-reason" in caplog.text


def test_google_login_unconfigured_returns_503():
    """With no client id configured the endpoint reports unavailable, not 401."""
    import api.auth as auth

    with patch.object(auth, "_google_client_id", ""):
        resp = _client().post("/api/auth/google", json={"id_token": "x"})

    assert resp.status_code == 503
