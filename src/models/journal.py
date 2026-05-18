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
