"""Tests for the stable per-memory ``public_id`` used in durable share links.

The public_id is generated once at row creation (DBMemory.default_factory),
carried on the Memory domain model, and surfaced through project serialization
so both the owner payload and the /api/share payload expose it.
"""

from models.project_db import DBMemory
from src.models.memory import Memory
from src.models.project import Project, ProjectItem
from src.project.project_io import ProjectIO


class TestDBMemoryPublicId:
    def test_public_id_assigned_on_construction(self):
        row = DBMemory(project_id=1, date="2026-05-29")
        assert row.public_id
        assert isinstance(row.public_id, str)
        assert len(row.public_id) >= 16

    def test_two_rows_get_distinct_public_ids(self):
        a = DBMemory(project_id=1, date="2026-05-29")
        b = DBMemory(project_id=1, date="2026-05-29")
        assert a.public_id != b.public_id

    def test_explicit_public_id_is_preserved(self):
        row = DBMemory(project_id=1, date="2026-05-29", public_id="fixed123")
        assert row.public_id == "fixed123"


class TestMemoryDataclassPublicId:
    def test_default_is_none(self):
        assert Memory(date="2026-05-29").public_id is None

    def test_can_be_set(self):
        assert Memory(date="2026-05-29", public_id="abc").public_id == "abc"


class TestSerializationExposesPublicId:
    def _project_with_memory(self, **mem_kwargs):
        mem = Memory(date="2026-05-29", **mem_kwargs)
        item = ProjectItem(item_type="memory", memory=mem)
        return Project(name="test", items=[item])

    def test_serialise_includes_public_id(self):
        project = self._project_with_memory(public_id="pub-xyz")
        d = ProjectIO.to_dict(project)
        assert d["items"][0]["memory"]["public_id"] == "pub-xyz"

    def test_serialise_public_id_none_when_absent(self):
        project = self._project_with_memory()
        d = ProjectIO.to_dict(project)
        assert d["items"][0]["memory"]["public_id"] is None

    def test_round_trip_preserves_public_id(self):
        orig = ProjectItem(
            item_type="memory",
            memory=Memory(date="2026-05-29", public_id="pub-roundtrip"),
        )
        restored = ProjectIO._deserialise_item(ProjectIO._serialise_item(orig))
        assert restored.memory.public_id == "pub-roundtrip"
