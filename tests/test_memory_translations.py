"""Tests for memory translation endpoints and caching behaviour."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.memories import _utc_now


# ---------------------------------------------------------------------------
# Helpers — unit-test _utc_now and the translate_text helper in isolation
# ---------------------------------------------------------------------------

class TestUtcNowFormat:
    def test_ends_with_z(self):
        ts = _utc_now()
        assert ts.endswith("Z")

    def test_length(self):
        assert len(_utc_now()) == 20  # "YYYY-MM-DDTHH:MM:SSZ"


# ---------------------------------------------------------------------------
# translate_text helper — mock httpx to avoid real API calls
# ---------------------------------------------------------------------------

class TestTranslateText:
    @pytest.mark.anyio
    async def test_returns_translated_text(self):
        from api.translations import translate_text

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {"translations": [{"translatedText": "Bonjour"}]}
        }

        with patch("api.translations.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await translate_text("Hello", "fr")

        assert result == "Bonjour"

    @pytest.mark.anyio
    async def test_passes_source_lang_when_provided(self):
        from api.translations import translate_text

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {"translations": [{"translatedText": "Hola"}]}
        }

        with patch("api.translations.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await translate_text("Hello", "es", source_lang="en")

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["params"]["source"] == "en"

    @pytest.mark.anyio
    async def test_http_error_propagates(self):
        """A non-2xx Google response must raise, so get_translation's except
        fires, logs, and surfaces a 502 (the prod symptom in #24 / issue follow-up)."""
        import httpx
        from api.translations import translate_text

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=MagicMock()
            )
        )

        with patch("api.translations.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await translate_text("Hello", "pt")

    @pytest.mark.anyio
    async def test_no_source_lang_omits_source_param(self):
        from api.translations import translate_text

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {"translations": [{"translatedText": "Ciao"}]}
        }

        with patch("api.translations.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await translate_text("Hello", "it")

        call_kwargs = mock_client.post.call_args[1]
        assert "source" not in call_kwargs["params"]


# ---------------------------------------------------------------------------
# DBMemoryTranslation model — basic field access
# ---------------------------------------------------------------------------

class TestDBMemoryTranslation:
    def test_fields_set_correctly(self):
        from models.project_db import DBMemoryTranslation

        row = DBMemoryTranslation(
            memory_id=1,
            lang_code="fr",
            name="Bonjour",
            description="Un beau souvenir",
            created_at="2026-05-30T10:00:00Z",
        )
        assert row.memory_id == 1
        assert row.lang_code == "fr"
        assert row.name == "Bonjour"
        assert row.description == "Un beau souvenir"

    def test_name_and_description_nullable(self):
        from models.project_db import DBMemoryTranslation

        row = DBMemoryTranslation(memory_id=5, lang_code="de")
        assert row.name is None
        assert row.description is None


# ---------------------------------------------------------------------------
# Project languages field propagation
# ---------------------------------------------------------------------------

class TestProjectLanguages:
    def test_project_default_languages_empty(self):
        from src.models.project import Project

        p = Project(name="test")
        assert p.languages == []

    def test_project_languages_set(self):
        from src.models.project import Project

        p = Project(name="test", languages=["fr", "de"])
        assert p.languages == ["fr", "de"]

    def test_languages_serialised_in_to_dict(self):
        from src.project.project_io import ProjectIO
        from src.models.project import Project

        p = Project(name="trip", languages=["pt", "es"])
        d = ProjectIO.to_dict(p)
        assert d["languages"] == ["pt", "es"]

    def test_empty_languages_serialised_as_empty_list(self):
        from src.project.project_io import ProjectIO
        from src.models.project import Project

        p = Project(name="trip")
        d = ProjectIO.to_dict(p)
        assert d["languages"] == []
