"""Database repository for projects, activities, and the Strava cache.

Replaces ``ProjectIO`` for the FastAPI endpoints.

Public interface mirrors what the endpoints need:

    repo = ProjectRepo()
    with get_session() as sess:
        project = repo.get_project(sess, user_info_id, name)   # lazy-migrates if needed
        repo.save_project(sess, user_info_id, project)

All methods that write data call ``sess.commit()`` before returning.

``ProjectRepo`` itself has no logic — it composes the domain-specific mixins
below. See each mixin's module for the implementation of its methods.
"""
from __future__ import annotations

# Ensure all SQLModel table classes are registered with SQLAlchemy's metadata
# before any FK resolution happens at query time.
from models.user import UserInfo, StravaToken  # noqa: F401

from src.project.repo_core import ProjectCoreMixin, StaleWriteError, _compute_stats, _compute_counter_stats, _compute_low_res_geo
from src.project.repo_activities import ActivityMixin, _low_res_ep_json
from src.project.repo_items import ItemOrderingMixin
from src.project.repo_transfer import ImportExportMixin
from src.project.repo_row_mappers import RowMappersMixin

__all__ = [
    "ProjectRepo",
    "StaleWriteError",
    "_compute_stats",
    "_compute_counter_stats",
    "_compute_low_res_geo",
    "_low_res_ep_json",
]


class ProjectRepo(ProjectCoreMixin, ActivityMixin, ItemOrderingMixin, ImportExportMixin, RowMappersMixin):
    """All DB operations for projects and activities."""
