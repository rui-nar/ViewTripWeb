"""Journal Entry data model — a private owner-only note attached to a trip date."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class JournalEntry:
    id: Optional[int] = None
    project_id: Optional[int] = None
    date: str = ""                          # "YYYY-MM-DD" — mandatory
    time: Optional[str] = None              # "HH:MM" local time
    description: Optional[str] = None
    photos: List[str] = field(default_factory=list)  # base UUID filenames (no suffix)
    geo_mode: str = "start_of_day"          # "start_of_day" | "end_of_day" | "custom"
    lat: Optional[float] = None
    lon: Optional[float] = None

    def to_dict(self) -> dict:
        """Serialise to a dict that can be round-tripped via from_dict()."""
        return {
            "id": self.id,
            "date": self.date,
            "time": self.time,
            "description": self.description,
            "photos": self.photos,
            "geo_mode": self.geo_mode,
            "lat": self.lat,
            "lon": self.lon,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JournalEntry":
        """Create a JournalEntry instance from a dict produced by to_dict()."""
        return cls(
            id=d.get("id"),
            date=d.get("date", ""),
            time=d.get("time"),
            description=d.get("description"),
            photos=d.get("photos", []),
            geo_mode=d.get("geo_mode", "start_of_day"),
            lat=d.get("lat"),
            lon=d.get("lon"),
        )
