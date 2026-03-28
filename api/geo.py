"""GeoJSON endpoints — converts a project's tracks and segments to GeoJSON.

Routes:
    GET /api/geo/project?name=   — GeoJSON FeatureCollection for an open project
"""
from __future__ import annotations

import os
from typing import Annotated, Any, Dict, List

import polyline as polyline_lib
from models.db import get_session
from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import get_current_user
from src.models.great_circle import great_circle_points
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo

router = APIRouter(prefix="/api/geo", tags=["geo"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_repo = ProjectRepo()


def _legacy_path(user_id: str, name: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, name + ProjectIO.EXTENSION)


def _linestring(coords: List[List[float]], properties: Dict[str, Any]) -> Dict[str, Any]:
    """Build a GeoJSON Feature with a LineString geometry."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coords,  # [[lon, lat], ...]
        },
        "properties": properties,
    }


@router.get("/project")
def project_geo(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return a GeoJSON FeatureCollection for *name*.

    Each activity LineString has properties ``{"type": "activity", ...}``.
    Each connecting segment has properties ``{"type": "segment", ...}``.
    GeoJSON coordinates are [longitude, latitude] as per the spec.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    features: List[Dict[str, Any]] = []

    for item in project.items:
        if item.item_type == "activity":
            activity = project.activity_by_id(item.activity_id)
            if activity is None:
                continue

            if activity.summary_polyline:
                # Full GPS track — decode Google-encoded polyline
                decoded = polyline_lib.decode(activity.summary_polyline)
                coords = [[lon, lat] for lat, lon in decoded]
            elif activity.start_latlng and activity.end_latlng:
                # No polyline (GPX import / private activity) — straight line fallback
                coords = [
                    [activity.start_latlng[1], activity.start_latlng[0]],
                    [activity.end_latlng[1],   activity.end_latlng[0]],
                ]
            else:
                continue  # no coordinates at all

            if len(coords) < 2:
                continue
            features.append(_linestring(coords, {
                "type": "activity",
                "activity_id": activity.id,
                "name": activity.name,
                "sport_type": activity.type,
            }))

        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            # great_circle_points returns [(lat, lon), ...]
            pts = great_circle_points(
                seg.start.lat, seg.start.lon,
                seg.end.lat, seg.end.lon,
                n_points=50,
            )
            coords = [[lon, lat] for lat, lon in pts]
            if len(coords) < 2:
                continue
            features.append(_linestring(coords, {
                "type": "segment",
                "segment_type": seg.segment_type,
                "label": seg.label,
            }))

    return {"type": "FeatureCollection", "features": features}
