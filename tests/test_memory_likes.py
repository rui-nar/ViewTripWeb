"""Tests for memory like/comment count fields on the Memory domain model."""

import pytest

from src.models.memory import Memory


class TestMemoryModel:
    def test_default_comment_count_is_zero(self):
        mem = Memory(date="2026-05-29")
        assert mem.comment_count == 0

    def test_default_like_count_is_zero(self):
        mem = Memory(date="2026-05-29")
        assert mem.like_count == 0

    def test_comment_count_can_be_set(self):
        mem = Memory(date="2026-05-29", comment_count=3)
        assert mem.comment_count == 3

    def test_like_count_can_be_set(self):
        mem = Memory(date="2026-05-29", like_count=7)
        assert mem.like_count == 7

    def test_serialized_fields_include_counts(self):
        """project_io._serialise_item must include comment_count and like_count."""
        from src.project.project_io import ProjectIO
        from src.models.project import Project, ProjectItem

        mem = Memory(date="2026-05-29", comment_count=2, like_count=5)
        item = ProjectItem(item_type="memory", memory=mem)
        project = Project(name="test", items=[item])

        d = ProjectIO.to_dict(project)
        mem_dict = d["items"][0]["memory"]

        assert mem_dict["comment_count"] == 2
        assert mem_dict["like_count"] == 5

    def test_serialized_fields_default_to_zero(self):
        from src.project.project_io import ProjectIO
        from src.models.project import Project, ProjectItem

        mem = Memory(date="2026-05-29")
        item = ProjectItem(item_type="memory", memory=mem)
        project = Project(name="test", items=[item])

        d = ProjectIO.to_dict(project)
        mem_dict = d["items"][0]["memory"]

        assert mem_dict["comment_count"] == 0
        assert mem_dict["like_count"] == 0
