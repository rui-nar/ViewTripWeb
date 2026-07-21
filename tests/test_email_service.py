"""Unit tests for the transactional email service (issue #113).

No network, no DB — ConsoleEmailService never touches a socket, and
get_email_service()'s backend selection is exercised via monkeypatched env
vars. SmtpEmailService's actual `send()` isn't tested here (that would mean
either hitting a real relay or mocking aiosmtplib internals, which the issue
explicitly steers away from); its construction-from-env and the fact that
selecting it requires SMTP_HOST are covered instead.
"""
from __future__ import annotations

import logging

import pytest

import src.email.service as email_service
from src.email.service import (
    ConsoleEmailService,
    EmailMessage,
    SmtpEmailService,
    get_email_service,
)
from src.email.templates import render_invite_email


@pytest.fixture(autouse=True)
def _reset_service_singleton():
    """get_email_service() caches its choice at module scope — reset it
    around every test so one test's env vars can't leak into another's."""
    email_service._service = None
    yield
    email_service._service = None


class TestConsoleEmailService:
    @pytest.mark.anyio
    async def test_send_logs_and_does_not_raise(self, caplog):
        svc = ConsoleEmailService()
        with caplog.at_level(logging.INFO):
            await svc.send(EmailMessage(
                to="a@b.com", subject="Hi", text_body="body text",
                html_body="<p>body</p>"))

        assert "a@b.com" in caplog.text
        assert "Hi" in caplog.text
        assert "body text" in caplog.text


class TestGetEmailService:
    def test_defaults_to_console_when_smtp_host_unset(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)

        assert isinstance(get_email_service(), ConsoleEmailService)

    def test_picks_smtp_when_smtp_host_set(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

        assert isinstance(get_email_service(), SmtpEmailService)

    def test_is_a_singleton_within_a_process(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)

        assert get_email_service() is get_email_service()


class TestSmtpEmailServiceConstruction:
    def test_reads_config_from_env(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "2525")
        monkeypatch.setenv("SMTP_USERNAME", "user")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")
        monkeypatch.setenv("MAIL_FROM", "invites@example.com")

        svc = SmtpEmailService()

        assert svc._host == "smtp.example.com"
        assert svc._port == 2525
        assert svc._username == "user"
        assert svc._password == "pw"
        assert svc._mail_from == "invites@example.com"

    def test_mail_from_falls_back_to_username(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
        monkeypatch.delenv("MAIL_FROM", raising=False)

        assert SmtpEmailService()._mail_from == "user@example.com"

    def test_port_defaults_to_587(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.delenv("SMTP_PORT", raising=False)

        assert SmtpEmailService()._port == 587

    def test_missing_smtp_host_raises(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)

        with pytest.raises(KeyError):
            SmtpEmailService()


class TestRenderInviteEmail:
    def test_text_body_is_not_escaped(self):
        text, _ = render_invite_email(
            project_name="Trip & Co", owner_name="Ana <ana@x.com>",
            role="editor", join_url="http://x/join/abc")

        assert "Trip & Co" in text
        assert "Ana <ana@x.com>" in text
        assert "http://x/join/abc" in text
        assert "editor" in text

    def test_html_body_is_escaped(self):
        _, html = render_invite_email(
            project_name="Trip & Co", owner_name="Ana <ana@x.com>",
            role="viewer", join_url="http://x/join/abc")

        assert "Trip &amp; Co" in html
        assert "Ana &lt;ana@x.com&gt;" in html
        assert "<script" not in html
        # The link itself is not escaped — it must remain a working href.
        assert 'href="http://x/join/abc"' in html
        assert "viewer" in html
