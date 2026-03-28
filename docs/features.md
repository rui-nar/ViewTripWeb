# Features Overview

## Project Status

**Current Release**: v0.8.0
**Stack**: Flutter Web / Android / iOS + FastAPI backend

---

## Implemented Features

### Authentication
- Google OAuth login via native Google Sign-In (Flutter)
- Local email/password login and registration
- JWT-based API authentication (all endpoints require Bearer token)
- Session persistence (token stored in Flutter `SharedPreferences`)
- Update display name, change password (local accounts), delete account

### Project Management
- Create, list, delete projects
- Import existing `.gettracks` files
- Per-user project storage (isolated directories)

### Strava Integration
- OAuth 2.0 connect / disconnect flow (web-compatible — opens browser via `url_launcher`)
- Per-user token storage in SQLite (`StravaToken` table)
- Automatic token refresh on expiry
- Sync all Strava activities into a project (paginated, 200/page)
- Force re-fetch individual activity (picks up Strava edits)
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
- Re-fetch activity from Strava (per-item refresh button)
- Aggregate stats header (total distance, moving time, elevation gain)
- Pan-to-activity on tap
- Activity selection highlights the corresponding track on map

### Map
- flutter_map with OpenStreetMap tiles
- `CancellableNetworkTileProvider` (cancels in-flight tile requests on pan/zoom)
- Activity tracks rendered as polylines (decoded from GeoJSON coordinates)
- Fallback: straight line from `start_latlng` → `end_latlng` for activities without polyline
- Connecting segments rendered as great-circle arcs (SLERP)
- Auto-fit bounds on project load
- Activity polylines: orange (`#F97316`)
- Segment arcs: grey (`#888888`, dashed weight)
- Orange dot marker synced to elevation chart hover/click position

### Elevation Chart
- Concatenated elevation profile across all project activities
- LTTB downsampling to 300 points (~56× rendering speedup vs raw data)
- `fl_chart` line chart with fill
- Hover/click moves an orange dot marker on the map to the matching GPS coordinate
- Click on map updates a vertical dashed cursor on the chart
- Wide layout: 160 px strip below map
- Narrow layout: inside draggable bottom sheet

### Connecting Segments CRUD
- "Add connecting segment after" button on each activity tile — auto-populates both start (end of predecessor) and end (start of successor) coordinates
- "Add connecting segment" button at the end of the list
- Segment types: Flight, Train, Bus, Boat
- Optional label (e.g. "Basel → Paris")
- Start/end coordinate fields with map-click picker
- Arc preview on map while editing
- Edit existing segment
- Delete segment

### Share Links
- Generate a public share link for a project
- Shared view renders the map + elevation chart without authentication

### Wide / Narrow Responsive Layout
- ≥720 px: side-by-side (activity panel left, map + elevation chart right)
- <720 px: full-screen map with draggable bottom sheet overlay

### Settings
- Manage Strava connection
- Account settings (display name, password, delete account)

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

### Performance
- Infinite scroll / pagination on import screen
- Lazy loading of elevation data

### Deployment
- Postgres support for multi-server deployments
- Helm chart / cloud deployment guide
