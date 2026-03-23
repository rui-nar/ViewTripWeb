"""Serialize / deserialize a Project to/from a .gettracks JSON file."""

from __future__ import annotations

import json
from typing import Any, Dict

from src.models.activity import Activity
from src.models.project import (
    ConnectingSegment,
    Project,
    ProjectFilterState,
    ProjectItem,
    SegmentEndpoint,
)


class ProjectIO:
    """Load and save .gettracks project files."""

    EXTENSION = ".gettracks"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def new(name: str) -> Project:
        """Create a blank in-memory project with the given name."""
        return Project(name=name)

    @staticmethod
    def save(project: Project, path: str) -> None:
        """Serialise *project* to *path* as indented JSON."""
        data: Dict[str, Any] = {
            "version": project.version,
            "name": project.name,
            "filter_state": {
                "start_date": project.filter_state.start_date,
                "end_date": project.filter_state.end_date,
                "activity_types": project.filter_state.activity_types,
            },
            "items": [ProjectIO._serialise_item(i) for i in project.items],
            "activities": [a.to_strava_dict() for a in project.activities],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    @staticmethod
    def to_dict(project: Project) -> Dict[str, Any]:
        """Return project data as a dict suitable for the REST API.

        Differs from :meth:`save` in one way: ``elevation_profile`` is
        converted from the storage format ``{"distances_km": [...], "elevations_m": [...]}``
        to a list of ``[dist_km, elev_m]`` pairs so the Flutter client can
        iterate over them directly.
        """
        def _ep_pairs(a: Activity) -> Any:
            if not a.elevation_profile:
                return None
            return [list(pair) for pair in zip(a.elevation_profile[0], a.elevation_profile[1])]

        activities_out = []
        for a in project.activities:
            d = a.to_strava_dict()
            d["elevation_profile"] = _ep_pairs(a)
            activities_out.append(d)

        return {
            "version": project.version,
            "name": project.name,
            "filter_state": {
                "start_date": project.filter_state.start_date,
                "end_date": project.filter_state.end_date,
                "activity_types": project.filter_state.activity_types,
            },
            "items": [ProjectIO._serialise_item(i) for i in project.items],
            "activities": activities_out,
        }

    @staticmethod
    def load(path: str) -> Project:
        """Deserialise a .gettracks file and return a :class:`Project`."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        fs_raw = data.get("filter_state", {}) or {}
        filter_state = ProjectFilterState(
            start_date=fs_raw.get("start_date"),
            end_date=fs_raw.get("end_date"),
            activity_types=fs_raw.get("activity_types"),
        )

        activities = []
        for raw in data.get("activities", []):
            try:
                activities.append(Activity.from_strava_api(raw))
            except Exception:
                pass  # skip corrupt entries silently

        items = [ProjectIO._deserialise_item(i) for i in data.get("items", [])]

        project = Project(
            name=data.get("name", "Untitled"),
            version=data.get("version", 1),
            items=items,
            filter_state=filter_state,
            activities=activities,
        )
        project.rebuild_map()
        return project

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialise_item(item: ProjectItem) -> Dict[str, Any]:
        d: Dict[str, Any] = {"item_type": item.item_type}
        if item.item_type == "activity":
            d["activity_id"] = item.activity_id
        else:
            seg = item.segment
            d["segment"] = {
                "id": seg.id,
                "segment_type": seg.segment_type,
                "label": seg.label,
                "start": {
                    "lat": seg.start.lat,
                    "lon": seg.start.lon,
                    "source": seg.start.source,
                },
                "end": {
                    "lat": seg.end.lat,
                    "lon": seg.end.lon,
                    "source": seg.end.source,
                },
            }
        return d

    @staticmethod
    def _deserialise_item(d: Dict[str, Any]) -> ProjectItem:
        if d.get("item_type") == "activity":
            return ProjectItem(item_type="activity", activity_id=d.get("activity_id"))
        # segment
        sd = d.get("segment", {})
        seg = ConnectingSegment(
            id=sd.get("id", ""),
            segment_type=sd.get("segment_type", "flight"),
            label=sd.get("label", ""),
            start=SegmentEndpoint(
                lat=sd.get("start", {}).get("lat", 0.0),
                lon=sd.get("start", {}).get("lon", 0.0),
                source=sd.get("start", {}).get("source", "auto"),
            ),
            end=SegmentEndpoint(
                lat=sd.get("end", {}).get("lat", 0.0),
                lon=sd.get("end", {}).get("lon", 0.0),
                source=sd.get("end", {}).get("source", "auto"),
            ),
        )
        return ProjectItem(item_type="segment", segment=seg)
