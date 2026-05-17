"""Schema contract tests — catch DBProject column/serializer drift before it reaches prod.

These tests are the CI-time counterpart to the startup _check_schema_contract() guard.
They verify that:
  1. Every column on DBProject is registered in exactly one registry set.
  2. Every entry in _PROJECT_SERIALIZED_FIELDS actually exists as a DB column.
  3. The two registry sets are mutually exclusive.
  4. The startup guard itself passes against the current model.

A new column added to DBProject without updating the registries will fail
test_every_column_is_registered, prompting the developer to decide whether
the column belongs in _PROJECT_SERIALIZED_FIELDS (surfaced to the app) or
_PROJECT_INFRA_FIELDS (infrastructure / audit / cache).
"""

import pytest

from models.project_db import (
    DBProject,
    _PROJECT_INFRA_FIELDS,
    _PROJECT_SERIALIZED_FIELDS,
    _check_schema_contract,
)


class TestDBProjectRegistry:
    def test_every_column_is_registered(self):
        """Every column on DBProject must appear in exactly one registry set."""
        actual = {col.name for col in DBProject.__table__.columns}
        known = _PROJECT_SERIALIZED_FIELDS | _PROJECT_INFRA_FIELDS
        unregistered = actual - known
        assert not unregistered, (
            f"Column(s) added to DBProject without updating the schema contract registry: "
            f"{sorted(unregistered)}. "
            "Add each column to _PROJECT_SERIALIZED_FIELDS (if _row_to_project reads it) "
            "or _PROJECT_INFRA_FIELDS (if it is infrastructure-only) in models/project_db.py."
        )

    def test_serialized_fields_exist_as_columns(self):
        """No phantom entries in _PROJECT_SERIALIZED_FIELDS."""
        actual = {col.name for col in DBProject.__table__.columns}
        phantom = _PROJECT_SERIALIZED_FIELDS - actual
        assert not phantom, (
            f"_PROJECT_SERIALIZED_FIELDS references field(s) absent from DBProject: "
            f"{sorted(phantom)}. Update the registry to match the current model."
        )

    def test_infra_fields_exist_as_columns(self):
        """No phantom entries in _PROJECT_INFRA_FIELDS."""
        actual = {col.name for col in DBProject.__table__.columns}
        phantom = _PROJECT_INFRA_FIELDS - actual
        assert not phantom, (
            f"_PROJECT_INFRA_FIELDS references field(s) absent from DBProject: "
            f"{sorted(phantom)}. Update the registry to match the current model."
        )

    def test_no_overlap_between_serialized_and_infra(self):
        """A column must not appear in both sets."""
        overlap = _PROJECT_SERIALIZED_FIELDS & _PROJECT_INFRA_FIELDS
        assert not overlap, (
            f"Column(s) registered in both _PROJECT_SERIALIZED_FIELDS and "
            f"_PROJECT_INFRA_FIELDS: {sorted(overlap)}. Each column must appear in exactly one set."
        )

    def test_check_schema_contract_passes(self):
        """The startup guard must not raise against the current model."""
        _check_schema_contract()
