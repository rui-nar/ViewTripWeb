"""Regression tests for issue #28 Part A — the anonymous share-view ciphertext leak.

Before this fix, `GET /api/share/{token}` and `.../meta` serialised encrypted
memory `name`/`description` verbatim (raw `v1.<b64>.<b64>` envelopes) into the
JSON response, and `GET /api/share/{token}/memories/{id}/translations/{lang}`
sent that same ciphertext straight to the Google Translate client with no
guard — unlike the owner-authenticated equivalent in api/memories.py (issue
#27). These tests prove both paths are now safe.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_optional_current_user
from api.share import invalidate_share_cache, router as share_router
from models.project_db import DBMemory, DBProject, DBProjectItem
from models.user import UserInfo

_ENVELOPE_NAME = "v1.YWJj.ZGVm"
_ENVELOPE_DESC = "v1.eGl6.enp6"


def _seed(engine, *, name=None, description=None, languages=None):
    with Session(engine) as sess:
        u = UserInfo(display_name="Owner", email="o@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(
            user_info_id=u.id, name="Trip", share_token="tok_full",
            languages_json=json.dumps(languages or []),
        )
        sess.add(proj); sess.commit(); sess.refresh(proj)

        mem = DBMemory(project_id=proj.id, public_id="pub1", date="2024-06-01",
                        name=name, description=description)
        sess.add(mem); sess.commit(); sess.refresh(mem)

        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="memory", memory_id=mem.id))
        sess.commit()
        return mem.id


@pytest.fixture
def share_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    def _make(**kwargs):
        mem_id = _seed(engine, **kwargs)
        invalidate_share_cache("tok_full")
        app = FastAPI()
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.include_router(share_router)
        return TestClient(app), mem_id

    return _make


# ── shared_project / shared_project_meta: never leak raw ciphertext ───────────

class TestSharedProjectStripsCiphertext:
    def test_encrypted_name_is_not_returned_raw(self, share_client):
        client, _mem_id = share_client(name=_ENVELOPE_NAME, description="plain notes")
        resp = client.get("/api/share/tok_full")
        assert resp.status_code == 200
        assert "v1." not in resp.text
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] is None
        assert mem["description"] == "plain notes"
        assert mem["name_encrypted"] is True
        assert "description_encrypted" not in mem

    def test_encrypted_description_is_not_returned_raw(self, share_client):
        client, _mem_id = share_client(name="A place", description=_ENVELOPE_DESC)
        resp = client.get("/api/share/tok_full")
        assert resp.status_code == 200
        assert "v1." not in resp.text
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] == "A place"
        assert mem["description"] is None
        assert mem["description_encrypted"] is True
        assert "name_encrypted" not in mem

    def test_both_encrypted_are_stripped(self, share_client):
        client, _mem_id = share_client(name=_ENVELOPE_NAME, description=_ENVELOPE_DESC)
        resp = client.get("/api/share/tok_full")
        assert "v1." not in resp.text
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] is None
        assert mem["description"] is None
        assert mem["name_encrypted"] is True
        assert mem["description_encrypted"] is True

    def test_plaintext_memory_is_unaffected(self, share_client):
        client, _mem_id = share_client(name="A place", description="Some notes")
        resp = client.get("/api/share/tok_full")
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] == "A place"
        assert mem["description"] == "Some notes"
        assert "name_encrypted" not in mem
        assert "description_encrypted" not in mem


class TestSharedProjectMetaStripsCiphertext:
    def test_encrypted_fields_not_returned_raw(self, share_client):
        client, _mem_id = share_client(name=_ENVELOPE_NAME, description=_ENVELOPE_DESC)
        resp = client.get("/api/share/tok_full/meta")
        assert resp.status_code == 200
        assert "v1." not in resp.text
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] is None
        assert mem["description"] is None

    def test_plaintext_memory_is_unaffected(self, share_client):
        client, _mem_id = share_client(name="A place", description="Some notes")
        resp = client.get("/api/share/tok_full/meta")
        mem = next(it["memory"] for it in resp.json()["items"] if it["item_type"] == "memory")
        assert mem["name"] == "A place"
        assert mem["description"] == "Some notes"


# ── shared_get_translation: same encryption guard as the owner path (#27) ─────

class TestSharedGetTranslationRejectsEncrypted:
    def test_rejects_when_name_is_an_envelope(self, share_client):
        client, mem_id = share_client(name=_ENVELOPE_NAME, description="plain",
                                       languages=["fr"])
        with patch("api.share.translate_text", new_callable=AsyncMock) as mock_translate:
            resp = client.get(f"/api/share/tok_full/memories/{mem_id}/translations/fr")
        assert resp.status_code == 409
        mock_translate.assert_not_called()

    def test_rejects_when_description_is_an_envelope(self, share_client):
        client, mem_id = share_client(name="A place", description=_ENVELOPE_DESC,
                                       languages=["fr"])
        with patch("api.share.translate_text", new_callable=AsyncMock) as mock_translate:
            resp = client.get(f"/api/share/tok_full/memories/{mem_id}/translations/fr")
        assert resp.status_code == 409
        mock_translate.assert_not_called()

    def test_plaintext_memory_still_translates(self, share_client):
        client, mem_id = share_client(name="A place", description="Some notes",
                                       languages=["fr"])
        mock_translate = AsyncMock(side_effect=["Un lieu", "Quelques notes"])
        with patch("api.share.translate_text", mock_translate):
            resp = client.get(f"/api/share/tok_full/memories/{mem_id}/translations/fr")
        assert resp.status_code == 200
        assert resp.json() == {"lang_code": "fr", "name": "Un lieu", "description": "Quelques notes"}
