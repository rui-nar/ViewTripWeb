"""Tests for track-style persistence: Project model defaults, to_dict serialisation."""

from src.models.project import Project
from src.project.project_io import ProjectIO


class TestTrackStyleDefaults:
    def test_default_track_color(self):
        p = Project(name="test")
        assert p.track_color == "#F97316"

    def test_default_track_width(self):
        p = Project(name="test")
        assert p.track_width == 2.5

    def test_default_alternating_false(self):
        p = Project(name="test")
        assert p.alternating_track_colors is False


class TestTrackStyleSerialisation:
    def test_to_dict_includes_track_color(self):
        p = Project(name="test", track_color="#1D4ED8")
        d = ProjectIO.to_dict(p)
        assert d["track_color"] == "#1D4ED8"

    def test_to_dict_includes_track_width(self):
        p = Project(name="test", track_width=4.0)
        d = ProjectIO.to_dict(p)
        assert d["track_width"] == 4.0

    def test_to_dict_includes_alternating(self):
        p = Project(name="test", alternating_track_colors=True)
        d = ProjectIO.to_dict(p)
        assert d["alternating_track_colors"] is True

    def test_to_dict_default_track_color_is_orange(self):
        d = ProjectIO.to_dict(Project(name="test"))
        assert d["track_color"] == "#F97316"

    def test_to_dict_all_three_fields_present(self):
        d = ProjectIO.to_dict(Project(name="test"))
        assert "track_color" in d
        assert "track_width" in d
        assert "alternating_track_colors" in d
