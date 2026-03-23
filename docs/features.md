# Features Overview

## Project Status

**Current Release**: v0.7.0
**Stack**: Flutter Web + Reflex/FastAPI backend

---

## Implemented Features

### Authentication
- Google OAuth login / registration via Reflex
- JWT-based API authentication (all endpoints require Bearer token)
- Session persistence (token stored in Flutter `SharedPreferences`)

### Project Management
- Create, list, delete projects
- Import existing `.gettracks` files
- Per-user project storage (isolated directories)

### Strava Integration
- OAuth 2.0 connect / disconnect flow (web-compatible — opens browser via `url_launcher`)
- Per-user token storage in SQLite (`StravaToken` table)
- Automatic token refresh on expiry
- Sync all Strava activities into a project (paginated, 200/page)
- Browse Strava activities with filters:
  - Date range (start/end)
  - Activity type (Run, Ride, Hike, …)
  - `in_project` flag shows which activities are already added

### Activity Import Screen (`/strava-import`)
- Date range picker (calendar)
- Activity type filter chips (populated from fetched results)
- Multi-select with checkboxes
- Select All / Clear buttons
- "Already in project" indicator (greyed + checkmark)
- "Add N to project" action button

### Project Screen (`/app`)
- Ordered items list (activities + connecting segments)
- Drag-to-reorder (`ReorderableListView`)
- Delete any item (activity or segment)
- Aggregate stats header (total distance, moving time, elevation gain)
- Pan-to-activity on tap

### Map
- flutter_map with OpenStreetMap tiles
- `CancellableNetworkTileProvider` (cancels in-flight tile requests on pan/zoom)
- Activity tracks rendered as polylines (decoded from `summary_polyline`)
- Fallback: straight line from `start_latlng` → `end_latlng` for activities without polyline
- Connecting segments rendered as great-circle arcs (SLERP)
- Auto-fit bounds on project load
- Activity polylines: orange (`#F97316`)
- Segment arcs: grey (`#888888`, dashed weight)

### Elevation Chart
- Concatenated elevation profile across all project activities
- `fl_chart` line chart with fill
- Wide layout: 160 px strip below map
- Narrow layout: inside draggable bottom sheet

### Connecting Segments CRUD
- Add segment at end of list (or at specific position)
- Segment types: Flight, Train, Bus, Boat
- Optional label (e.g. "Basel → Paris")
- Start/end lat/lon fields (auto-populated from adjacent activity endpoints)
- Edit existing segment
- Delete segment

### Wide / Narrow Responsive Layout
- ≥720 px: side-by-side (activity panel left, map + elevation chart right)
- <720 px: full-screen map with draggable bottom sheet overlay

---

## Planned Features

### GPX Export
- Export merged project as a valid GPX file
- Connecting segments as great-circle interpolated trackpoints
- Export dialog with options

### Activity Caching
- Cache Strava activity data locally to reduce API calls
- Background sync

### Advanced Filtering
- Filter by distance, duration, elevation gain
- Save and restore filter presets

### Segment Improvements
- Map-click to pick coordinates for segment endpoints
- Visual arc preview before confirming

### Performance
- Infinite scroll / pagination on import screen
- Lazy loading of elevation data

### Deployment
- Postgres support for multi-server deployments
- Helm chart / cloud deployment guide
