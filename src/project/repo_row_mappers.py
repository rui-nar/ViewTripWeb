"""Static DB-row → domain-object mappers used by ``_row_to_project``.

Part of the ``ProjectRepo`` mixin split — see ``src/project/project_repo.py``
for the composed class and module docstring.
"""
from __future__ import annotations

import json

from models.project_db import DBEncounter, DBJournalEntry, DBMemory, DBPerson, DBPersonGroup
from src.models.encounter import Encounter
from src.models.journal import JournalEntry
from src.models.memory import Memory
from src.models.person import Person
from src.models.person_group import PersonGroup
from src.models.project import ConnectingSegment, SegmentEndpoint


class RowMappersMixin:
    """Static row → domain-object mappers for memories, journals, people, groups, encounters, segments."""

    @staticmethod
    def _row_to_journal(row: DBJournalEntry) -> JournalEntry:
        return JournalEntry(
            id=row.id,
            project_id=row.project_id,
            date=row.date,
            time=row.time,
            description=row.description,
            photos=json.loads(row.photos_json or "[]"),
            geo_mode=row.geo_mode,
            lat=row.lat,
            lon=row.lon,
        )

    @staticmethod
    def _row_to_person(row: DBPerson) -> Person:
        return Person(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            email=row.email,
            phone=row.phone,
            polarsteps=row.polarsteps,
            notes=row.notes,
            avatar_photo=row.avatar_photo,
            socials=json.loads(row.socials_json) if row.socials_json else [],
            nationalities=json.loads(row.nationalities_json) if row.nationalities_json else [],
            residence=row.residence,
            group_id=row.group_id,
        )

    @staticmethod
    def _row_to_group(row: DBPersonGroup) -> PersonGroup:
        return PersonGroup(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            nationalities=json.loads(row.nationalities_json) if row.nationalities_json else [],
            socials=json.loads(row.socials_json) if row.socials_json else [],
        )

    @staticmethod
    def _row_to_encounter(row: DBEncounter) -> Encounter:
        return Encounter(
            id=row.id,
            project_id=row.project_id,
            person_id=row.person_id,
            group_id=row.group_id,
            date=row.date,
            time=row.time,
            description=row.description,
            geo_mode=row.geo_mode,
            lat=row.lat,
            lon=row.lon,
        )

    @staticmethod
    def _row_to_memory(row: DBMemory) -> Memory:
        return Memory(
            id=row.id,
            public_id=row.public_id,
            project_id=row.project_id,
            name=row.name,
            date=row.date,
            time=row.time,
            description=row.description,
            photos=json.loads(row.photos_json or "[]"),
            geo_mode=row.geo_mode,
            lat=row.lat,
            lon=row.lon,
        )

    @staticmethod
    def _json_to_segment(segment_json: str) -> ConnectingSegment:
        """Deserialise a segment JSON blob back to a ConnectingSegment."""
        sd = json.loads(segment_json) if segment_json else {}
        return ConnectingSegment(
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
            route_degraded=sd.get("route_degraded", False),
        )
