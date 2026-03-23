# ViewTripWeb — Development Plan

## Overview

ViewTripWeb is a self-hostable web application to assemble multi-sport GPS journey files from Strava activities, with connecting transport segments, elevation profiles, and GPX export.

**Stack**: Flutter Web (frontend) · Reflex/FastAPI (backend) · SQLite · Strava API

---

## Completed Milestones

### v0.5.0 — Flutter Client with Auth, Project Picker, App Screen
- Google OAuth login / registration
- JWT-based API authentication
- Project list screen (create, delete, import `.gettracks`)
- App screen: map + activity panel
- `CancellableNetworkTileProvider` on tile layer

### v0.6.0 — App Screen Fixes + Strava OAuth
- Fixed `ProjectIO.new()` (was missing, caused 500 on project creation)
- Fixed `elevation_profile` format mismatch (split arrays → `[[dist, elev]]` pairs)
- `GET /api/geo/project` — GeoJSON endpoint with polyline decoding
- Strava OAuth connect / callback / status / disconnect
- `StravaToken` DB table + Alembic migration
- Strava status card on projects screen

### v0.7.0 — Strava Import Screen + Activity/Segment CRUD
- **Bug fix**: blank map tracks for activities without `summary_polyline` (straight-line fallback)
- **Elevation chart**: moved to right side below map (wide layout)
- `GET /api/strava/activities` with date/type filters + `in_project` flag
- `POST /api/projects/{name}/activities` — add selected activities
- `DELETE /api/projects/{name}/items/{index}` — remove item
- `PUT /api/projects/{name}/items/reorder` — drag-to-reorder
- Segments CRUD: create, update, delete connecting segments
- Flutter: `StravaImportScreen` with date range, type chips, multi-select
- Flutter: `SegmentDialog` (Flight/Train/Bus/Boat, auto-populates from adjacent activities)
- Flutter: `ReorderableListView` for activity panel
- Flutter: delete buttons per item; "Add connecting segment" button

---

## Roadmap

### Next: GPX Export

**Goal**: user can export the assembled project as a valid GPX file.

Backend (`api/projects.py`):
- `GET /api/projects/{name}/export` — build GPX from project
  - Activities: fetch stream data via `get_activity_streams()` for full GPS track, or fall back to decoded `summary_polyline`
  - Connecting segments: interpolate great-circle arc as dense trackpoints
  - Single `<trk>` with one `<trkseg>` per item, or merged into one continuous segment

Flutter:
- Export button in AppBar
- Download response as `{project_name}.gpx` via `dart:html` anchor trick (web)

### Upcoming

#### Activity Caching
- Cache raw Strava activity JSON per user to reduce API calls on repeated opens
- Invalidate on sync

#### Import Screen Pagination
- Infinite scroll or "Load more" on Strava import screen (currently 100/page max)

#### Map Interaction
- Click on map to pick coordinates for segment start/end (instead of typing lat/lon)
- Hover/tap a track to highlight the corresponding item in the list

#### Segment Arc Preview
- Show the great-circle arc on the map while editing a segment in the dialog

#### Advanced Filters
- Filter Strava import by distance, duration, elevation gain
- Save and restore filter presets between sessions

#### Settings Screen
- Manage Strava connection
- Set default date range for import
- Theme selection

#### Deployment Improvements
- Postgres support (switch SQLModel DB URL)
- Reverse proxy example (nginx config)
- Cloud run / Fly.io deployment guide

---

## Development Best Practices

- **Ask before moving to the next phase** — confirm scope before starting new work
- **Commit at logical checkpoints** — one commit per feature/fix, clear messages
- **Backend first** — implement and verify API endpoints before wiring Flutter
- **No orphan code** — remove or update any file that references the old desktop app
- **Keep docs in sync** — update this plan, architecture.md, and features.md when shipping
