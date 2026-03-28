# Architecture Overview

## Current Status

**Release**: v0.8.0
**Stack**: Flutter Web / Android / iOS (frontend) + FastAPI (backend) + SQLite

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Flutter — Dart, flutter_map, provider, go_router |
| Backend | Python 3.11, FastAPI, SQLModel |
| Database | SQLite (managed by Alembic) |
| Auth | Google OAuth + local email/password · JWT (PyJWT, HS256) |
| Strava | OAuth 2.0, per-user token in `StravaToken` DB table |
| Maps | flutter_map + OpenStreetMap tiles |
| Charts | fl_chart (elevation profile, LTTB downsampled) |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser / Mobile                                       │
│                                                         │
│  ┌─────────────────────────┐                            │
│  │   Flutter App           │                            │
│  │   (Web / Android / iOS) │                            │
│  │                         │                            │
│  │  Screens:               │   HTTP + JWT Bearer        │
│  │  - Login / Register     │ ──────────────────────►    │
│  │  - Projects list        │                        ┌───┴──────────────────┐
│  │  - App screen           │ ◄──────────────────── │  FastAPI              │
│  │  - Strava import        │   JSON responses       │  Python 3.11         │
│  └─────────────────────────┘                        │                      │
│                                                      │  Routers:            │
│                                                      │  /api/auth/          │
│                                                      │  /api/projects/      │
│                                                      │  /api/geo/           │
│                                                      │  /api/strava/        │
│                                                      │  /api/share/         │
│                                                      │                      │
│                                                      │  ┌────────────────┐  │
│                                                      │  │   SQLite DB     │  │
│                                                      │  │  LocalUser      │  │
│                                                      │  │  UserInfo       │  │
│                                                      │  │  StravaToken    │  │
│                                                      │  │  DBProject      │  │
│                                                      │  │  DBActivity     │  │
│                                                      │  └────────────────┘  │
│                                                      │                      │
│                                                      │  data/users/*/       │
│                                                      │  projects/*.gettracks│
│                                                      └──────────────────────┘
└─────────────────────────────────────────────────────────┘
```

---

## Backend Layers

### 1. Authentication (`api/auth.py`, `api/deps.py`)

Two auth providers, both issuing a JWT on success:

- **Local**: `POST /api/auth/token` — username + bcrypt password verification against `LocalUser` table
- **Google**: `POST /api/auth/google` — verifies Google `id_token` via `google-auth` library; creates shadow `LocalUser` + `UserInfo` on first login

`create_access_token(user_info)` → signed JWT (PyJWT, HS256, 7-day expiry).
All endpoints require `Authorization: Bearer <jwt>` via the `get_current_user()` FastAPI dependency.

Strava OAuth: user identity passed as JWT in OAuth `state` param — stateless callback resolves the user by verifying the token.

### 2. Projects (`api/projects.py`)

REST endpoints for project lifecycle and item management:
- CRUD for projects (list, create, get, delete, import `.gettracks`)
- Activities: add selected activities from Strava
- Items: delete by index, reorder (from/to index)
- Segments: create, update, delete connecting segments (flight/train/bus/boat)

All project data stored as `.gettracks` JSON files per user under `data/users/{user_id}/projects/`.

### 3. GeoJSON (`api/geo.py`)

`GET /api/geo/project?name=`:
- Loads project file, iterates ordered `items`
- Activities: decodes `summary_polyline` (Google encoded polyline via `polyline` lib) → `[[lon, lat], ...]`
  - Fallback: two-point line from `start_latlng`/`end_latlng` if no polyline
- Segments: SLERP great-circle arc via `great_circle_points()` → `[[lon, lat], ...]`
- Returns GeoJSON FeatureCollection with `type` property (`"activity"` or `"segment"`) on each Feature
- Includes `elevation_profile` and `start_latlng`/`end_latlng` in Feature properties for Flutter to consume

### 4. Strava (`api/strava.py`)

- **Connect**: builds Strava OAuth URL, appends JWT as `state`
- **Callback**: exchanges code, stores/updates `StravaToken` row in DB, redirects to Flutter origin
- **Status/Disconnect**: read/delete token row
- **Activities** (`GET /api/strava/activities`): paginated browse with `start_date`, `end_date`, `types` filters and `in_project` flag
- **Sync** (`POST /api/projects/{name}/strava/sync`): fetches all Strava activities (200/page), merges new ones into project

Token refresh: refreshed token is persisted back to DB after each request.

### 5. Core Business Logic (`src/`)

| Module | Purpose |
|---|---|
| `src/api/strava_client.py` | StravaAPI — HTTP client with retry + rate limiting |
| `src/auth/oauth.py` | OAuth2Session — Strava authorization URL + code exchange |
| `src/config/settings.py` | Config — dot-notation access to `config/config.json` |
| `src/filters/filter_engine.py` | FilterCriteria + FilterEngine.apply() |
| `src/models/activity.py` | Activity model — `from_strava_api()`, `to_strava_dict()`, `to_dict()` |
| `src/models/project.py` | Project, ProjectItem, ConnectingSegment, SegmentEndpoint |
| `src/models/great_circle.py` | SLERP great-circle arc generation |
| `src/project/project_io.py` | ProjectIO — load/save/new + `to_dict()` serialisation |
| `src/project/project_repo.py` | ProjectRepo — DB-backed CRUD for projects + activities |

---

## Frontend Architecture (Flutter)

### State Management

Provider pattern — each screen has a `ChangeNotifier`:

| Notifier | Responsibility |
|---|---|
| `AuthNotifier` | Login/logout/session restore; holds current user + JWT |
| `ProjectsNotifier` | Project list; create/delete; Strava connect status |
| `ProjectNotifier` | Open project data (activities, items, geo); all CRUD ops; elevation cursor |
| `StravaImportNotifier` | Strava activity browser state (filters, selection, add) |

### Routing (`app_router.dart`)

`GoRouter` with auth guard:
- `/login`, `/register` — public
- `/projects` — project picker + Strava connect card
- `/app?project={name}` — main project screen
- `/strava-import?project={name}` — Strava activity import screen

### App Screen Layout

**Wide (≥720 px):**
```
┌─────────────────┬──────────────────────────────────────┐
│  ActivityPanel  │  FlutterMap (OpenStreetMap tiles)    │
│  (280 px)       │  + Polyline layer                    │
│                 ├──────────────────────────────────────┤
│  - Stats header │  ElevationChart (160 px, fl_chart)   │
│  - Reorderable  │  LTTB-downsampled, elevation cursor  │
│    items list   │  synced to map orange dot marker     │
│  - Add segment  │                                      │
└─────────────────┴──────────────────────────────────────┘
```

**Narrow (<720 px):**
```
┌──────────────────────────────────────────────────────┐
│  FlutterMap (full screen)                            │
│                                                      │
│  ┌─ DraggableScrollableSheet ───────────────────┐   │
│  │  ActivityPanel (with elevation chart)         │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

### Elevation Chart Performance

The elevation chart uses **LTTB (Largest-Triangle-Three-Buckets)** downsampling to reduce data from up to ~17 000 points to 300 rendered points, giving a ~56× rendering speedup while preserving visual shape. Hover/click on the chart moves an orange dot marker on the map to the corresponding GPS coordinate.

---

## Database Schema

Managed by SQLModel + Alembic migrations:

```sql
CREATE TABLE localuser (
    id            INTEGER PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash BLOB,
    enabled       BOOLEAN
);

CREATE TABLE userinfo (
    id            INTEGER PRIMARY KEY,
    local_auth_id INTEGER REFERENCES localuser(id),
    google_sub    TEXT,
    display_name  TEXT,
    email         TEXT,
    avatar_url    TEXT,
    auth_provider TEXT    -- "local" | "google"
);

CREATE TABLE stravatoken (
    id              INTEGER PRIMARY KEY,
    user_info_id    INTEGER UNIQUE REFERENCES userinfo(id),
    access_token    TEXT,
    refresh_token   TEXT,
    expires_at      REAL    -- Unix timestamp
);
```

Run migrations with `alembic upgrade head`.

---

## Data Flow

### Open Project
```
Flutter: context.go('/app?project=foo')
  └─> ProjectNotifier.load('foo')
       └─> parallel:
            ├─ GET /api/projects/foo  →  {activities, items, ...}
            └─ GET /api/geo/project?name=foo  →  GeoJSON FeatureCollection
       └─> MapPanel renders polylines
       └─> ActivityPanel renders reorderable items list
       └─> ElevationChart: full elevation_profile built from GeoJSON
            → LTTB downsampled to 300 points for fl_chart
            → per-activity tracks indexed for cursor → map dot sync
```

### Import from Strava
```
Flutter: context.go('/strava-import?project=foo')
  └─> StravaImportNotifier.load(projectName: 'foo')
       └─> GET /api/strava/activities?project=foo&per_page=100
            └─> StravaAPI.get_activities() with date/type params
            └─> FilterEngine.apply() for type filter
            └─> in_project flag per activity
  └─> User selects activities → StravaImportNotifier.addSelected('foo')
       └─> POST /api/projects/foo/activities {activities: [...]}
            └─> Activity.from_strava_api() for each
            └─> project.add_activities() → saves .gettracks file
```

### Strava OAuth
```
Flutter: GET /api/strava/connect → {url: "https://www.strava.com/oauth/authorize?...&state=JWT"}
  └─> url_launcher opens URL in browser
       └─> User authorises on Strava
       └─> Strava redirects to /api/strava/callback?code=...&state=JWT
            └─> decode JWT → user_info_id
            └─> OAuth2Session.exchange_code(code) → token_data
            └─> upsert StravaToken row in DB
            └─> RedirectResponse to Flutter origin /?strava=connected
```

---

## Security

- JWT signed with `JWT_SECRET` env var (fallback dev value — always set in production); HS256, 7-day expiry
- Strava OAuth state param carries JWT — callback verifies signature before trusting user identity
- All project endpoints scoped to authenticated user's directory (`data/users/{sub}/`)
- `config/config.json` gitignored; secrets never in source or logs
- Passwords hashed with bcrypt (cost factor from `bcrypt.gensalt()`)
- HTTPS enforced by Strava on OAuth redirect

---

## Known Limitations / Future Work

- No GPX export yet (data model ready; export module not implemented)
- Activity pagination on import screen is per-page only (no infinite scroll)
- No offline mode / activity caching
- Single-server SQLite (no horizontal scaling without switching to Postgres)
