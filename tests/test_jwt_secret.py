"""The session signing key must be configured, or nothing starts (issue #156).

`api/deps.py` used to fall back to a constant that ships in this public
repository. Every deployment that never set `JWT_SECRET` therefore signed tokens
with a key anyone could read, and the token payload carries `is_admin`. The
failure mode was silence — the app worked perfectly and said nothing.

These lock the fallback out permanently. `conftest.py` sets a real key for the
suite, so each case here clears or overrides it explicitly.
"""
from __future__ import annotations

import jwt
import pytest

from api.deps import _PUBLISHED_DEFAULT, create_access_token, decode_token, jwt_secret
from models.user import UserInfo


class TestJwtSecret:
    def test_unset_is_refused(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="JWT_SECRET is not configured"):
            jwt_secret()

    def test_blank_is_refused(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "   ")
        with pytest.raises(RuntimeError):
            jwt_secret()

    def test_the_old_published_default_is_refused_by_name(self, monkeypatch):
        """Copying it out of an old README is as forgeable as never setting it."""
        monkeypatch.setenv("JWT_SECRET", _PUBLISHED_DEFAULT)
        with pytest.raises(RuntimeError):
            jwt_secret()

    def test_the_error_names_the_fix(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError) as exc:
            jwt_secret()
        assert "openssl rand -hex 32" in str(exc.value)

    def test_a_configured_key_is_returned_stripped(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "  a-real-key  ")
        assert jwt_secret() == "a-real-key"

    def test_read_per_call_not_cached_at_import(self, monkeypatch):
        """So a restart rotates the key, and a test can change it."""
        monkeypatch.setenv("JWT_SECRET", "first")
        assert jwt_secret() == "first"
        monkeypatch.setenv("JWT_SECRET", "second")
        assert jwt_secret() == "second"


class TestTokensUseIt:
    def _user(self):
        return UserInfo(id=1, email="a@b.c", display_name="A",
                        auth_provider="local", is_admin=False)

    def test_a_token_signed_with_another_key_is_rejected(self, monkeypatch):
        """The point of the whole change: a key we did not choose must not verify."""
        monkeypatch.setenv("JWT_SECRET", "the-real-key" * 4)
        forged = jwt.encode({"sub": "1", "is_admin": True},
                            _PUBLISHED_DEFAULT, algorithm="HS256")
        with pytest.raises(Exception) as exc:
            decode_token(forged)
        assert "401" in str(exc.value) or "Invalid token" in str(exc.value)

    def test_round_trip_under_a_configured_key(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "another-real-key" * 4)
        token = create_access_token(self._user())
        assert decode_token(token)["sub"] == "1"

    def test_rotating_the_key_invalidates_existing_tokens(self, monkeypatch):
        """Operators need to know this: rotation signs everyone out."""
        monkeypatch.setenv("JWT_SECRET", "key-one" * 8)
        token = create_access_token(self._user())
        assert decode_token(token)["sub"] == "1"

        monkeypatch.setenv("JWT_SECRET", "key-two" * 8)
        with pytest.raises(Exception):
            decode_token(token)

    def test_signing_without_a_key_raises_rather_than_signing(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            create_access_token(self._user())
