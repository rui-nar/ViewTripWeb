"""Server-side logging of Polarsteps client failures (issue #205, Unit B).

Before this, ``src/api/polarsteps_client.py`` had no logger at all — a fetch
failure, an auth rejection, or a malformed response only ever reached the one
user who triggered it, as an ``HTTPException.detail`` string built further up
the call chain. These tests assert the client itself now leaves a trace.
"""
from __future__ import annotations

import logging

import pytest
import requests

from src.api.polarsteps_client import PolarstepsClient

_LOGGER = "src.api.polarsteps_client"


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, raise_json=False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise requests.exceptions.JSONDecodeError("bad json", "doc", 0)
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def _client() -> PolarstepsClient:
    return PolarstepsClient("1|token")


def test_get_logs_warning_on_401(caplog):
    c = _client()
    c._session.get = lambda url, params=None, timeout=None: _FakeResp(status_code=401)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(PermissionError):
            c._get("/users/1")

    assert "token rejected" in caplog.text
    assert "endpoint=/users/{id}" in caplog.text


def test_get_logs_warning_on_http_error(caplog):
    c = _client()
    c._session.get = lambda url, params=None, timeout=None: _FakeResp(status_code=500)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(requests.HTTPError):
            c._get("/users/1")

    assert "polarsteps request failed" in caplog.text
    assert "status=500" in caplog.text


def test_get_logs_warning_on_malformed_json(caplog):
    c = _client()
    c._session.get = lambda url, params=None, timeout=None: _FakeResp(
        status_code=200, raise_json=True
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(ValueError):
            c._get("/users/1")

    assert "malformed JSON" in caplog.text


def test_get_logs_warning_on_connection_error(caplog):
    c = _client()

    def _boom(url, params=None, timeout=None):
        raise requests.ConnectionError("boom")

    c._session.get = _boom

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(requests.ConnectionError):
            c._get("/users/1")

    assert "polarsteps request failed" in caplog.text


def test_get_succeeds_without_logging(caplog):
    """Sanity check: the happy path stays silent (no WARNING noise)."""
    c = _client()
    c._session.get = lambda url, params=None, timeout=None: _FakeResp(
        status_code=200, json_data={"ok": True}
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = c._get("/users/1")

    assert result == {"ok": True}
    assert caplog.text == ""
