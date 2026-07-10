"""Serialize / deserialize a Project to/from a .viewtrip JSON file."""

from __future__ import annotations

import json
from typing import Any, Dict

from src.models.activity import Activity
from src.models.encounter import Encounter
from src.models.journal import JournalEntry
from src.models.memory import Memory
from src.models.person import Person
from src.models.person_group import PersonGroup
from src.models.project import (
    ConnectingSegment,
    DayMeta,
    day_counters_to_json,
    DEFAULT_SLEEPING_OPTIONS,
    Project,
    ProjectFilterState,
    ProjectItem,
    SegmentEndpoint,
)


def _person_to_dict(p: Person) -> Dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "email": p.email,
        "phone": p.phone,
        "polarsteps": p.polarsteps,
        "notes": p.notes,
        "avatar_photo": p.avatar_photo,
        "socials": p.socials,
        "nationalities": p.nationalities,
        "residence": p.residence,
        "group_id": p.group_id,
    }


def _person_from_dict(d: Dict[str, Any]) -> Person:
    return Person(
        id=d.get("id"),
        name=d.get("name"),
        email=d.get("email"),
        phone=d.get("phone"),
        polarsteps=d.get("polarsteps"),
        notes=d.get("notes"),
        avatar_photo=d.get("avatar_photo"),
        socials=d.get("socials") or [],
        nationalities=d.get("nationalities") or [],
        residence=d.get("residence"),
        group_id=d.get("group_id"),
    )


def _group_to_dict(g: PersonGroup) -> Dict[str, Any]:
    return {
        "id": g.id,
        "name": g.name,
        "nationalities": g.nationalities,
        "socials": g.socials,
    }


def _group_from_dict(d: Dict[str, Any]) -> PersonGroup:
    return PersonGroup(
        id=d.get("id"),
        name=d.get("name"),
        nationalities=d.get("nationalities") or [],
        socials=d.get("socials") or [],
    )


class ProjectIO:
    """Load and save .viewtrip project files."""

    EXTENSION = ".viewtrip"
    LEGACY_EXTENSION = ".gettracks"

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
            "trip_start": project.trip_start,
            "trip_end": project.trip_end,
            "filter_state": {
                "start_date": project.filter_state.start_date,
                "end_date": project.filter_state.end_date,
                "activity_types": project.filter_state.activity_types,
            },
            "items": [ProjectIO._serialise_item(i) for i in project.items],
            "activities": [a.to_strava_dict() for a in project.activities],
            "people": [_person_to_dict(p) for p in project.people],
            "groups": [_group_to_dict(g) for g in project.groups],
            "day_meta": {
                dk: {
                    **{k: v for k, v in {
                        "difficulty": dm.difficulty, "sleeping": dm.sleeping,
                        "weather": dm.weather, "journal": dm.journal,
                    }.items() if v is not None},
                    **({"tags": dm.tags} if dm.tags else {}),
                }
                for dk, dm in project.day_meta.items()
            },
            "sleeping_options": project.sleeping_options,
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
            # Prefer the full profile; fall back to the downsampled low-res copy
            # so meta / low-res responses (where the full profile is deferred)
            # still render the chart immediately. The client overwrites it when
            # the full profile loads in the background.
            ep = a.elevation_profile or getattr(a, "elevation_profile_low_res", None)
            if not ep:
                return None
            return [list(pair) for pair in zip(ep[0], ep[1])]

        activities_out = []
        for a in project.activities:
            d = a.to_strava_dict()
            d["elevation_profile"] = _ep_pairs(a)
            activities_out.append(d)

        return {
            "version": project.version,
            "name": project.name,
            "trip_start": project.trip_start,
            "trip_end": project.trip_end,
            "filter_state": {
                "start_date": project.filter_state.start_date,
                "end_date": project.filter_state.end_date,
                "activity_types": project.filter_state.activity_types,
            },
            "items": [ProjectIO._serialise_item(i) for i in project.items],
            "activities": activities_out,
            "people": [_person_to_dict(p) for p in project.people],
            "groups": [_group_to_dict(g) for g in project.groups],
            "day_meta": {
                dk: {
                    **{k: v for k, v in {
                        "difficulty": dm.difficulty, "sleeping": dm.sleeping,
                        "weather": dm.weather, "journal": dm.journal,
                    }.items() if v is not None},
                    **({"tags": dm.tags} if dm.tags else {}),
                    **({"counters": day_counters_to_json(dm.counters)} if dm.counters else {}),
                }
                for dk, dm in project.day_meta.items()
            },
            "sleeping_options": project.sleeping_options,
            "sleeping_option_groups": project.sleeping_option_groups,
            "counters": [{"name": c.name, "start": c.start} for c in project.counters],
            "track_color": project.track_color,
            "track_secondary_color": project.track_secondary_color,
            "track_width": project.track_width,
            "alternating_track_colors": project.alternating_track_colors,
            "elevation_chart_color": project.elevation_chart_color,
            "elevation_chart_show_line": project.elevation_chart_show_line,
            "languages": project.languages,
        }

    @staticmethod
    def load(path: str) -> Project:
        """Deserialise a .viewtrip (or legacy .gettracks) file and return a :class:`Project`."""
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

        raw_dm = data.get("day_meta") or {}
        day_meta = {
            dk: DayMeta(
                difficulty=v.get("difficulty"),
                sleeping=v.get("sleeping"),
                weather=v.get("weather"),
                journal=v.get("journal"),
                tags=v.get("tags") or [],
            )
            for dk, v in raw_dm.items()
        }
        raw_opts = data.get("sleeping_options")
        sleeping_options = (
            list(raw_opts) if isinstance(raw_opts, list) and raw_opts
            else list(DEFAULT_SLEEPING_OPTIONS)
        )

        people = [_person_from_dict(p) for p in data.get("people", [])]
        groups = [_group_from_dict(g) for g in data.get("groups", [])]

        project = Project(
            name=data.get("name", "Untitled"),
            version=data.get("version", 1),
            trip_start=data.get("trip_start"),
            items=items,
            filter_state=filter_state,
            activities=activities,
            people=people,
            groups=groups,
            day_meta=day_meta,
            sleeping_options=sleeping_options,
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
        elif item.item_type == "memory" and item.memory is not None:
            mem = item.memory
            d["memory"] = {
                "id": mem.id,
                "public_id": mem.public_id,
                "name": mem.name,
                "date": mem.date,
                "time": mem.time,
                "description": mem.description,
                "photos": mem.photos,
                "geo_mode": mem.geo_mode,
                "lat": mem.lat,
                "lon": mem.lon,
                "comment_count": mem.comment_count,
                "like_count": mem.like_count,
            }
        elif item.item_type == "journal" and item.journal is not None:
            j = item.journal
            d["journal"] = {
                "id": j.id,
                "date": j.date,
                "time": j.time,
                "description": j.description,
                "photos": j.photos,
                "geo_mode": j.geo_mode,
                "lat": j.lat,
                "lon": j.lon,
            }
        elif item.item_type == "encounter" and item.encounter is not None:
            e = item.encounter
            d["encounter"] = {
                "id": e.id,
                "person_id": e.person_id,
                "group_id": e.group_id,
                "date": e.date,
                "time": e.time,
                "description": e.description,
                "geo_mode": e.geo_mode,
                "lat": e.lat,
                "lon": e.lon,
            }
        else:
            seg = item.segment
            d["segment"] = {
                "id": seg.id,
                "segment_type": seg.segment_type,
                "label": seg.label,
                "date": seg.date,
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
                "route_mode": seg.route_mode,
                "train_number": seg.train_number,
                "hafas_provider": seg.hafas_provider,
                "route_polyline": seg.route_polyline,
                "route_status": seg.route_status,
                "route_error": seg.route_error,
                "route_started_at": seg.route_started_at,
                "route_degraded": seg.route_degraded,
            }
        return d

    @staticmethod
    def _deserialise_item(d: Dict[str, Any]) -> ProjectItem:
        if d.get("item_type") == "activity":
            return ProjectItem(item_type="activity", activity_id=d.get("activity_id"))
        if d.get("item_type") == "memory":
            md = d.get("memory", {})
            mem = Memory(
                id=md.get("id"),
                public_id=md.get("public_id"),
                name=md.get("name"),
                date=md.get("date", ""),
                time=md.get("time"),
                description=md.get("description"),
                photos=md.get("photos", []),
                geo_mode=md.get("geo_mode", "start_of_day"),
                lat=md.get("lat"),
                lon=md.get("lon"),
            )
            return ProjectItem(item_type="memory", memory=mem)
        if d.get("item_type") == "journal":
            jd = d.get("journal", {})
            jentry = JournalEntry(
                id=jd.get("id"),
                date=jd.get("date", ""),
                time=jd.get("time"),
                description=jd.get("description"),
                photos=jd.get("photos", []),
                geo_mode=jd.get("geo_mode", "start_of_day"),
                lat=jd.get("lat"),
                lon=jd.get("lon"),
            )
            return ProjectItem(item_type="journal", journal=jentry)
        if d.get("item_type") == "encounter":
            ed = d.get("encounter", {})
            enc = Encounter(
                id=ed.get("id"),
                person_id=ed.get("person_id"),
                group_id=ed.get("group_id"),
                date=ed.get("date", ""),
                time=ed.get("time"),
                description=ed.get("description"),
                geo_mode=ed.get("geo_mode", "start_of_day"),
                lat=ed.get("lat"),
                lon=ed.get("lon"),
            )
            return ProjectItem(item_type="encounter", encounter=enc)
        # segment
        sd = d.get("segment", {})
        seg = ConnectingSegment(
            id=sd.get("id", ""),
            segment_type=sd.get("segment_type", "flight"),
            label=sd.get("label", ""),
            date=sd.get("date"),
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
            route_mode=sd.get("route_mode", "great_circle"),
            train_number=sd.get("train_number"),
            hafas_provider=sd.get("hafas_provider"),
            route_polyline=sd.get("route_polyline"),
            route_status=sd.get("route_status", "idle"),
            route_error=sd.get("route_error"),
            route_started_at=sd.get("route_started_at"),
        )
        return ProjectItem(item_type="segment", segment=seg)
