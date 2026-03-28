"""Public share endpoints — no authentication required.

Routes:
    GET /api/share/{token}      — project details for a shared link
    GET /api/share/{token}/geo  — GeoJSON for a shared project
"""
from __future__ import annotations

from typing import Any, Dict, List

import polyline as polyline_lib
from models.db import get_session
from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from models.project_db import DBProject
from src.models.great_circle import great_circle_points
from src.project.project_repo import ProjectRepo

router = APIRouter(prefix="/api/share", tags=["share"])

_repo = ProjectRepo()


def _get_project_by_token(token: str):
    """Look up a project by share_token; raise 404 if not found."""
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(DBProject.share_token == token)
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shared project not found",
            )
        project = _repo.get_project_by_id(sess, row.id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared project not found",
        )
    return project


@router.get("/{token}")
def shared_project(token: str):
    """Return project details (same shape as GET /api/projects/{name})."""
    project = _get_project_by_token(token)
    return _repo.to_dict(project)


@router.get("/{token}/geo")
def shared_project_geo(token: str):
    """Return GeoJSON FeatureCollection for a shared project."""
    project = _get_project_by_token(token)

    features: List[Dict[str, Any]] = []

    for item in project.items:
        if item.item_type == "activity":
            activity = project.activity_by_id(item.activity_id)
            if activity is None:
                continue

            if activity.summary_polyline:
                decoded = polyline_lib.decode(activity.summary_polyline)
                coords = [[lon, lat] for lat, lon in decoded]
            elif activity.start_latlng and activity.end_latlng:
                coords = [
                    [activity.start_latlng[1], activity.start_latlng[0]],
                    [activity.end_latlng[1],   activity.end_latlng[0]],
                ]
            else:
                continue

            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "activity",
                    "activity_id": activity.id,
                    "name": activity.name,
                    "sport_type": activity.type,
                },
            })

        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            pts = great_circle_points(
                seg.start.lat, seg.start.lon,
                seg.end.lat, seg.end.lon,
                n_points=50,
            )
            coords = [[lon, lat] for lat, lon in pts]
            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "segment",
                    "segment_type": seg.segment_type,
                    "label": seg.label,
                },
            })

    return {"type": "FeatureCollection", "features": features}
