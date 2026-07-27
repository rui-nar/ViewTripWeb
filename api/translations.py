"""Google Translate helper used by memory translation endpoints."""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from src.utils.metrics import outcome_for_status, track_external

_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
_GOOGLE_API_KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "")

_log = logging.getLogger(__name__)

if not _GOOGLE_API_KEY:
    _log.warning(
        "GOOGLE_TRANSLATE_API_KEY is not set — translation endpoints will fail at runtime"
    )


async def translate_text(
    text: str, target_lang: str, source_lang: Optional[str] = None
) -> str:
    """Translate *text* to *target_lang* via the Google Translate v2 REST API.

    Raises httpx.HTTPStatusError on API errors (caller should surface as 502).
    """
    params: dict = {
        "q": text,
        "target": target_lang,
        "key": _GOOGLE_API_KEY,
        "format": "text",
    }
    if source_lang:
        params["source"] = source_lang

    async with httpx.AsyncClient(timeout=10.0) as client:
        with track_external("google_translate", "/translate") as call:
            r = await client.post(_TRANSLATE_URL, params=params)
            call.outcome = outcome_for_status(r.status_code)
            r.raise_for_status()
        return r.json()["data"]["translations"][0]["translatedText"]
