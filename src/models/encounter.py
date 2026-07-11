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

    def to_dict(self) -> dict:
        """Serialise to a dict that can be round-tripped via from_dict()."""
        return {
            "id": self.id,
            "person_id": self.person_id,
            "group_id": self.group_id,
            "date": self.date,
            "time": self.time,
            "description": self.description,
            "geo_mode": self.geo_mode,
            "lat": self.lat,
            "lon": self.lon,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Encounter":
        """Create an Encounter instance from a dict produced by to_dict()."""
        return cls(
            id=d.get("id"),
            person_id=d.get("person_id"),
            group_id=d.get("group_id"),
            date=d.get("date", ""),
            time=d.get("time"),
            description=d.get("description"),
            geo_mode=d.get("geo_mode", "start_of_day"),
            lat=d.get("lat"),
            lon=d.get("lon"),
        )
