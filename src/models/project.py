"""Project data model — a named, ordered journey of activities and connecting segments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from src.models.activity import Activity
from src.models.memory import Memory

SegmentType = Literal["train", "flight", "boat", "bus"]

DEFAULT_SLEEPING_OPTIONS = [
    "Camping", "Bivouac", "Shelter",
    "Pension/Guesthouse", "Hotel", "Apartment",
]

DifficultyLevel = Literal["easy", "normal", "hard", "super_hard"]
WeatherCondition = Literal["hot", "clear", "cloudy", "some_rain", "heavy_rain"]


@dataclass
class DayMeta:
    """User-authored metadata for a single trip day."""
    difficulty: Optional[DifficultyLevel] = None
    sleeping: Optional[str] = None
    weather: Optional[WeatherCondition] = None
    journal: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class SegmentEndpoint:
    lat: float
    lon: float
    source: Literal["auto", "manual"] = "auto"


@dataclass
class ConnectingSegment:
    """A manually-defined great-circle segment between two project items."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    segment_type: SegmentType = "flight"
    start: SegmentEndpoint = field(default_factory=lambda: SegmentEndpoint(0.0, 0.0))
    end: SegmentEndpoint = field(default_factory=lambda: SegmentEndpoint(0.0, 0.0))
    label: str = ""   # e.g. "Basel → Paris (TGV)"
    date: Optional[str] = None  # ISO date "YYYY-MM-DD"
    # Rail-track fields — only relevant for segment_type == "train"
    route_mode: Literal["great_circle", "rail"] = "great_circle"
    train_number: Optional[str] = None      # e.g. "ICE 596"
    hafas_provider: Optional[str] = None    # e.g. "db"
    route_polyline: Optional[str] = None    # JSON-encoded [[lon,lat],…], stored once


@dataclass
class ProjectItem:
    """One entry in the project's ordered item list."""
    item_type: Literal["activity", "segment", "memory"]
    activity_id: Optional[int] = None
    segment: Optional[ConnectingSegment] = None
    memory: Optional[Memory] = None


@dataclass
class ProjectFilterState:
    """Serialised FilterWidget state, stored per project."""
    start_date: Optional[str] = None    # "YYYY-MM-DD"
    end_date: Optional[str] = None      # "YYYY-MM-DD"
    activity_types: Optional[List[str]] = None  # None = all types


@dataclass
class Project:
    """In-memory representation of a .gettracks file."""
    name: str
    version: int = 1
    items: List[ProjectItem] = field(default_factory=list)
    filter_state: ProjectFilterState = field(default_factory=ProjectFilterState)
    trip_start: Optional[str] = None  # ISO "YYYY-MM-DD" — overrides inferred day-1 date
    # Day metadata keyed by "YYYY-MM-DD"
    day_meta: Dict[str, DayMeta] = field(default_factory=dict)
    # Project-specific list of sleeping options
    sleeping_options: List[str] = field(default_factory=lambda: list(DEFAULT_SLEEPING_OPTIONS))
    # Full Strava data cached here for offline use
    activities: List[Activity] = field(default_factory=list)
    memories: List[Memory] = field(default_factory=list)
    # Derived lookup — rebuilt after load, not serialised
    _activity_map: Dict[int, Activity] = field(
        default_factory=dict, repr=False, compare=False
    )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def rebuild_map(self) -> None:
        """Rebuild the id → Activity lookup after loading or merging."""
        self._activity_map = {a.id: a for a in self.activities if a.id is not None}

    def activity_by_id(self, aid: int) -> Optional[Activity]:
        if not self._activity_map:
            self.rebuild_map()
        return self._activity_map.get(aid)

    def ordered_activities(self) -> List[Activity]:
        """Activity objects in project item order (segments excluded)."""
        result = []
        for item in self.items:
            if item.item_type == "activity" and item.activity_id is not None:
                a = self.activity_by_id(item.activity_id)
                if a is not None:
                    result.append(a)
        return result

    def add_activities(self, new_activities: List[Activity]) -> int:
        """Merge new activities into the project pool and append new ones to items.

        Returns the count of activities actually added (not already present).
        """
        self.rebuild_map()
        existing_ids = {a.id for a in self.activities if a.id is not None}
        added = 0
        for act in sorted(new_activities, key=lambda a: a.start_date):
            if act.id not in existing_ids:
                self.activities.append(act)
                self._activity_map[act.id] = act
                existing_ids.add(act.id)
                self.items.append(ProjectItem(item_type="activity", activity_id=act.id))
                added += 1
        return added

    def remove_item(self, index: int) -> None:
        """Remove item at *index* from the ordered list (does not remove activity data)."""
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def move_item(self, from_index: int, to_index: int) -> None:
        """Move item from *from_index* to *to_index* (before the element currently there)."""
        n = len(self.items)
        if from_index == to_index or not (0 <= from_index < n):
            return
        to_index = max(0, min(n - 1, to_index))
        item = self.items.pop(from_index)
        self.items.insert(to_index, item)

    def sort_activities_by_date(self) -> None:
        """Sort activity slots by start_date; segment positions are preserved by index."""
        self._sort_activity_slots(key=lambda a: a.start_date)

    def sort_activities_by_name(self) -> None:
        """Sort activity slots by name; segment positions are preserved by index."""
        self._sort_activity_slots(key=lambda a: a.name.lower())

    def _sort_activity_slots(self, key) -> None:
        activity_items = [item for item in self.items if item.item_type == "activity"]
        activity_items.sort(
            key=lambda item: key(self.activity_by_id(item.activity_id))
            if item.activity_id and self.activity_by_id(item.activity_id) else ""
        )
        it = iter(activity_items)
        for i, item in enumerate(self.items):
            if item.item_type == "activity":
                self.items[i] = next(it)
