"""Memory data model — a user annotation attached to a trip date."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Memory:
    id: Optional[int] = None
    public_id: Optional[str] = None         # stable UUID for durable share links
    project_id: Optional[int] = None
    name: Optional[str] = None
    date: str = ""                          # "YYYY-MM-DD" — mandatory
    time: Optional[str] = None              # "HH:MM" local time
    description: Optional[str] = None
    photos: List[str] = field(default_factory=list)  # base UUID filenames (no suffix)
    geo_mode: str = "start_of_day"          # "start_of_day" | "end_of_day" | "custom"
    lat: Optional[float] = None
    lon: Optional[float] = None
    comment_count: int = 0
    like_count: int = 0

    def to_dict(self) -> dict:
        """Serialise to a dict that can be round-tripped via from_dict()."""
        return {
            "id": self.id,
            "public_id": self.public_id,
            "name": self.name,
            "date": self.date,
            "time": self.time,
            "description": self.description,
            "photos": self.photos,
            "geo_mode": self.geo_mode,
            "lat": self.lat,
            "lon": self.lon,
            "comment_count": self.comment_count,
            "like_count": self.like_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Memory":
        """Create a Memory instance from a dict produced by to_dict()."""
        return cls(
            id=d.get("id"),
            public_id=d.get("public_id"),
            name=d.get("name"),
            date=d.get("date", ""),
            time=d.get("time"),
            description=d.get("description"),
            photos=d.get("photos", []),
            geo_mode=d.get("geo_mode", "start_of_day"),
            lat=d.get("lat"),
            lon=d.get("lon"),
        )
