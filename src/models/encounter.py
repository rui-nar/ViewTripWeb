"""Encounter data model — meeting a person or group on a given day/place (issue #40, #56).

Owner-only, per-project. An encounter links one Person OR one PersonGroup to a day,
with an optional place (map pin, defaulting to the day's location) and a free-text
note. Exactly one of person_id/group_id is set. Rendered as an ordered project item,
like memories and journal entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Encounter:
    id: Optional[int] = None
    project_id: Optional[int] = None
    person_id: Optional[int] = None
    group_id: Optional[int] = None          # issue #56 — alternative to person_id
    date: str = ""                          # "YYYY-MM-DD" — mandatory
    time: Optional[str] = None              # "HH:MM" local time
    description: Optional[str] = None       # free-text note
    geo_mode: str = "start_of_day"          # "start_of_day" | "end_of_day" | "custom"
    lat: Optional[float] = None
    lon: Optional[float] = None
