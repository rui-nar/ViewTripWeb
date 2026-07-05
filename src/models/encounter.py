"""Encounter data model — meeting a person on a given day/place (issue #40).

Owner-only, per-project. An encounter links one Person to a day, with an optional
place (map pin, defaulting to the day's location) and a free-text note. Rendered
as an ordered project item, like memories and journal entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Encounter:
    id: Optional[int] = None
    project_id: Optional[int] = None
    person_id: Optional[int] = None
    date: str = ""                          # "YYYY-MM-DD" — mandatory
    time: Optional[str] = None              # "HH:MM" local time
    description: Optional[str] = None       # free-text note
    geo_mode: str = "start_of_day"          # "start_of_day" | "end_of_day" | "custom"
    lat: Optional[float] = None
    lon: Optional[float] = None
