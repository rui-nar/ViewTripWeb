# ViewTripWeb — Development Plan

## Overview

ViewTripWeb is a self-hostable web application to assemble multi-sport GPS journey files from Strava activities, with connecting transport segments, elevation profiles, and GPX export.

**Stack**: Flutter Web / Android / iOS (frontend) · FastAPI (backend) · SQLite · Strava API

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
- Bug fix: blank map tracks for activities without `summary_polyline` (straight-line fallback)
- Elevation chart moved to right side below map (wide layout)
- `GET /api/strava/activities` with date/type filters + `in_project` flag
- `POST /api/projects/{name}/activities` — add selected activities
- `DELETE /api/projects/{name}/items/{index}` — remove item
- `PUT /api/projects/{name}/items/reorder` — drag-to-reorder
- Segments CRUD: create, update, delete connecting segments
- Flutter: `StravaImportScreen` with date range, type chips, multi-select
- Flutter: `SegmentDialog` (Flight/Train/Bus/Boat, auto-populates from adjacent activities)
- Flutter: `ReorderableListView` for activity panel
- Share links: generate public read-only project URLs
- Force re-fetch individual Strava activity

### v0.8.0 — Reflex Removal + Performance + Bug Fixes
- **Backend rewrite**: removed Reflex entirely; pure FastAPI + uvicorn
  - Own `LocalUser` model (bcrypt, no reflex_local_auth dependency)
  - Own `get_session()` context manager (SQLModel Session, no rx.session())
  - JWT-only auth (no cookie sessions / LocalAuthSession)
  - All Reflex/reflex_local_auth imports removed from api/, alembic/, models/
  - Updated requirements: removed reflex, reflex-local-auth, reflex-google-auth, passlib; added sqlmodel, alembic, bcrypt, google-auth explicitly
  - Simplified Dockerfile: no Node.js, no Reflex frontend build — just uvicorn
  - Updated docker-compose.yml: one port (8000), persistent SQLite volume
- **Elevation chart cursor**: orange dot on map now correctly tracks hover/click on elevation chart
  - Root cause: Dart polyline decoder incompatible with Python `polyline` lib encoding
  - Fix: use GeoJSON coordinates (already decoded server-side) instead of re-decoding polyline in Dart
- **Elevation chart performance**: LTTB downsampling (300 points) gives ~56× speedup
  - Pre-built per-activity tracks in `ProjectNotifier` (one pass, no repeated allocation)
  - Min/max computed before downsampling; track lookup uses direct index pairing
- **Segment dialog auto-populate**: "Add connecting segment after" button on each activity tile
  - Start = `end_latlng` of that activity (was already working)
  - End = `start_latlng` of the following activity (now correctly wired via per-item `insertAfterIndex`)
- **Layout fix**: `LocationPickerDialog` `ElevatedButton` infinite-width crash on Flutter web

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
- Download response as `{project_name}.gpx` via `dart:html` anchor trick (web) / file save (mobile)

### Upcoming

#### Activity Caching
- Cache raw Strava activity JSON per user to reduce API calls on repeated opens
- Invalidate on sync

#### Import Screen Pagination
- Infinite scroll or "Load more" on Strava import screen (currently 100/page max)

#### Map Interaction
- Hover/tap a track to highlight the corresponding item in the list

#### Settings Screen
- Extend settings with default date range for import, theme selection

#### Deployment Improvements
- Postgres support (switch SQLModel DB URL)
- Reverse proxy example (nginx config)
- Cloud run / Fly.io deployment guide

---

## Development Best Practices

- **Ask before moving to the next phase** — confirm scope before starting new work
- **Commit at logical checkpoints** — one commit per feature/fix, clear messages
- **Backend first** — implement and verify API endpoints before wiring Flutter
- **No orphan code** — remove any file that references old dependencies
- **Keep docs in sync** — update this plan, architecture.md, and features.md when shipping
