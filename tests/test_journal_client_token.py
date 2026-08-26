"""Idempotency guard for journal entry creation.

The bug: journal entries had no uniqueness constraint at all — a
client-perceived timeout followed by a manual user retry created a genuine
duplicate row with no server-side guard. This mirrors the Polarsteps
duplicate-import defense on memory (see test_polarsteps_dedup.py):

  * a client-supplied ``client_token`` dedupes a retry via an upfront check;
  * the partial unique index (``project_id``, ``client_token``) forbids two
    entries sharing a token in the same project;
  * a TOCTOU race between the upfront check and the commit is recovered the
    same way create_memory's Polarsteps race is (issue found in this exact
    codebase, in this same audit) — never a raw 500;
  * a different token, or no token, still creates a genuinely separate entry.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.journal import router as journal_router
from models.project_db import DBJournalEntry, DBProject, DBProjectItem
from models.user import UserInfo


@pytest.fixture
def env(monkeypatch, tmp_path):
    """In-memory DB + journal TestClient for one user/project.

    Yields (client, user_id, project_id, engine).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)

    import api.journal as journal_mod
    monkeypatch.setattr(journal_mod, "_DATA_DIR", str(tmp_path))

    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        user = UserInfo(display_name="Alice", email="alice@example.com")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        user_id = user.id
        project = DBProject(user_info_id=user_id, name="My Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        project_id = project.id

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "email": "alice@example.com"}
    app.include_router(journal_router)
    client = TestClient(app)
    yield client, user_id, project_id, engine


def _counts(engine, project_id):
    with Session(engine) as sess:
        entries = len(sess.exec(
            select(DBJournalEntry).where(DBJournalEntry.project_id == project_id)
        ).all())
        items = len(sess.exec(
            select(DBProjectItem).where(DBProjectItem.project_id == project_id)
        ).all())
        return entries, items


def _body(**over):
    b = {"project_name": "My Trip", "date": "2026-03-04", "geo_mode": "custom",
         "description": "hi", "lat": 48.0, "lon": 8.9, "client_token": "tok-abc"}
    b.update(over)
    return b


# ── Upfront-check path ──────────────────────────────────────────────────────

class TestCreateJournalIdempotency:
    def test_new_token_inserts_one_entry_and_item(self, env):
        client, _, project_id, engine = env
        r = client.post("/api/journal/", json=_body())
        assert r.status_code == 201, r.text
        assert _counts(engine, project_id) == (1, 1)

    def test_retry_with_same_token_returns_existing_entry(self, env):
        client, _, project_id, engine = env
        r1 = client.post("/api/journal/", json=_body())
        eid = r1.json()["id"]
        r2 = client.post("/api/journal/", json=_body(description="changed"))
        assert r2.status_code == 201, r2.text
        assert r2.json()["id"] == eid          # same row
        assert _counts(engine, project_id) == (1, 1)  # no duplicate
        # The upfront check returns the row untouched — description unchanged.
        with Session(engine) as sess:
            assert sess.get(DBJournalEntry, eid).description == "hi"

    def test_different_token_creates_a_second_entry(self, env):
        client, _, project_id, engine = env
        r1 = client.post("/api/journal/", json=_body())
        r2 = client.post("/api/journal/", json=_body(client_token="tok-xyz", date="2026-03-05"))
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        assert _counts(engine, project_id) == (2, 2)

    def test_no_token_still_allows_two_distinct_entries(self, env):
        """A genuinely new entry must not become accidentally impossible to
        create on the same day/project just because idempotency exists."""
        client, _, project_id, engine = env
        r1 = client.post("/api/journal/", json=_body(client_token=None))
        r2 = client.post("/api/journal/", json=_body(client_token=None))
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        assert _counts(engine, project_id) == (2, 2)


# ── Defense-in-depth: partial unique index ──────────────────────────────────

class TestUniqueClientTokenIndex:
    def test_duplicate_token_in_project_rejected(self, env):
        _, _, project_id, engine = env
        with Session(engine) as sess:
            sess.add(DBJournalEntry(project_id=project_id, date="d", client_token="t1"))
            sess.commit()
            sess.add(DBJournalEntry(project_id=project_id, date="d2", client_token="t1"))
            with pytest.raises(IntegrityError):
                sess.commit()

    def test_null_tokens_are_exempt(self, env):
        _, _, project_id, engine = env
        with Session(engine) as sess:
            sess.add(DBJournalEntry(project_id=project_id, date="d", client_token=None))
            sess.add(DBJournalEntry(project_id=project_id, date="d", client_token=None))
            sess.commit()  # must not raise


# ── TOCTOU race: two concurrent creates with the same token ─────────────────

class TestConcurrentClientTokenRace:
    """`_find_by_client_token` (the app-level dedup check) and the commit
    that follows it are not atomic. If a second request with the same token
    commits in between, the first request's own commit now loses to the
    unique index and must recover the same "already created" response
    instead of a raw 500 — same fix already applied once in this codebase
    for create_memory's Polarsteps race."""

    def test_loser_of_the_race_returns_the_winners_id_not_500(self, env, monkeypatch):
        client, _, project_id, engine = env
        import api.journal as journal_mod

        # The row a *different* request already committed for this token,
        # landing after our own `_find_by_client_token` check ran but before
        # our commit — the exact TOCTOU window the bug lives in.
        with Session(engine) as sess:
            winner = DBJournalEntry(project_id=project_id, date="2026-03-04", client_token="tok-abc")
            sess.add(winner)
            sess.commit()
            sess.refresh(winner)
            winner_id = winner.id
            sess.add(DBProjectItem(project_id=project_id, position=0,
                                    item_type="journal", journal_id=winner_id))
            sess.commit()

        orig_find = journal_mod._find_by_client_token
        calls = {"n": 0}

        def flaky_find(sess, pid, token):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # the pre-commit check ran before the race landed
            return orig_find(sess, pid, token)

        monkeypatch.setattr(journal_mod, "_find_by_client_token", flaky_find)

        resp = client.post("/api/journal/", json=_body())

        assert resp.status_code == 201, resp.text
        assert resp.json()["id"] == winner_id
        assert _counts(engine, project_id) == (1, 1)  # no duplicate row or item

    def test_unrecoverable_integrity_error_still_propagates(self, env, monkeypatch):
        """If recovery can't find a winning row after all, the failure must
        still surface — never silently swallowed."""
        client, _, project_id, engine = env
        import api.journal as journal_mod

        # Both lookups miss, so the handler has no row to fall back to.
        monkeypatch.setattr(journal_mod, "_find_by_client_token", lambda sess, pid, token: None)
        # Force the commit to fail as if the unique index caught a race that,
        # in this contrived case, no query can see afterwards.
        real_commit = Session.commit
        state = {"n": 0}

        def flaky_commit(self):
            state["n"] += 1
            if state["n"] == 1:
                raise IntegrityError(
                    "INSERT INTO journalentry ...", {},
                    Exception("UNIQUE constraint failed: journalentry.project_id, journalentry.client_token"),
                )
            return real_commit(self)

        monkeypatch.setattr(Session, "commit", flaky_commit)

        no_raise_client = TestClient(client.app, raise_server_exceptions=False)
        resp = no_raise_client.post("/api/journal/", json=_body())

        assert resp.status_code == 500
        assert _counts(engine, project_id) == (0, 0)
