"""GeoJSON API routes for map rendering."""
import json
import os
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse

import polyline as polyline_codec
from src.models.great_circle import great_circle_points


def _activity_to_geojson_feature(activity) -> dict:
    """Convert an Activity's summary polyline to a GeoJSON LineString feature."""
    if activity.summary_polyline:
        coords = [[lon, lat] for lat, lon in polyline_codec.decode(activity.summary_polyline)]
    else:
        coords = []
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": str(activity.id),
            "name": activity.name,
            "type": activity.type,
        },
    }


def _segment_to_geojson_feature(segment) -> dict:
    """Convert a ConnectingSegment to a GeoJSON LineString (great-circle arc)."""
    pts = great_circle_points(
        segment.start.lat, segment.start.lon,
        segment.end.lat, segment.end.lon,
    )
    coords = [[lon, lat] for lat, lon in pts]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "type": "segment",
            "transport": segment.segment_type,
        },
    }


async def geo_project(request: Request) -> JSONResponse:
    """Return GeoJSON FeatureCollection for the current project."""
    from app.state import _active_project  # late import avoids circular dep
    features = []
    if _active_project:
        project = _active_project[0]
        for item in project.items:
            if item.item_type == "activity" and item.activity_id is not None:
                act = project.activity_by_id(item.activity_id)
                if act:
                    features.append(_activity_to_geojson_feature(act))
            elif item.item_type == "segment" and item.segment is not None:
                features.append(_segment_to_geojson_feature(item.segment))
    return JSONResponse({"type": "FeatureCollection", "features": features})


async def map_html(request: Request) -> HTMLResponse:
    """Serve the Leaflet map HTML page."""
    html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>html,body,#map{height:100%;margin:0;padding:0;}</style>
</head>
<body>
<div id="map"></div>
<script>
  const map = L.map('map').setView([48, 10], 4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);

  fetch('/api/geo/project')
    .then(r => r.json())
    .then(geojson => {
      if (!geojson.features.length) return;
      const layer = L.geoJSON(geojson, {
        style: f => ({
          color: f.properties.type === 'segment' ? '#888' : '#f97316',
          dashArray: f.properties.type === 'segment' ? '6 4' : null,
          weight: 3,
        })
      }).addTo(map);
      map.fitBounds(layer.getBounds());
    });
</script>
</body>
</html>"""
    return HTMLResponse(html)
