"""Tests for per-type style persistence (issue #95): Project model defaults,
to_dict serialisation."""

from src.models.project import Project
from src.project.project_io import ProjectIO


class TestTypeStylesDefaults:
    def test_default_color_by_type_false(self):
        p = Project(name="test")
        assert p.color_by_type is False

    def test_default_type_styles_empty(self):
        p = Project(name="test")
        assert p.type_styles == {}


class TestTypeStylesSerialisation:
    def test_to_dict_includes_color_by_type(self):
        p = Project(name="test", color_by_type=True)
        d = ProjectIO.to_dict(p)
        assert d["color_by_type"] is True

    def test_to_dict_includes_type_styles(self):
        p = Project(name="test", type_styles={"ride": {"color": "#4FC3F7", "style": "solid"}})
        d = ProjectIO.to_dict(p)
        assert d["type_styles"] == {"ride": {"color": "#4FC3F7", "style": "solid"}}

    def test_to_dict_default_type_styles_is_empty_dict(self):
        d = ProjectIO.to_dict(Project(name="test"))
        assert d["type_styles"] == {}

    def test_to_dict_default_color_by_type_is_false(self):
        d = ProjectIO.to_dict(Project(name="test"))
        assert d["color_by_type"] is False
