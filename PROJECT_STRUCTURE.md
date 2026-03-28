# ViewTripWeb — Project Structure

## Directory Layout

```
ViewTripWeb/
│
├── api/                          # FastAPI route handlers
│   ├── auth.py                   # Auth endpoints (local + Google → JWT)
│   ├── deps.py                   # JWT dependency (get_current_user, create_access_token)
│   ├── geo.py                    # GET /api/geo/project — GeoJSON builder
│   ├── projects.py               # Projects + items + segments CRUD
│   ├── router.py                 # Mounts all routers onto the FastAPI app
│   ├── share.py                  # Share-link endpoints
│   └── strava.py                 # Strava OAuth + activity sync
│
├── models/                       # SQLModel database models
│   ├── db.py                     # Engine + get_session() context manager
│   ├── project_db.py             # DBProject, DBActivity, DBProjectItem, DBStravaCache
│   └── user.py                   # LocalUser, UserInfo, StravaToken
│
├── src/                          # Core business logic (shared by API and tests)
│   ├── api/
│   │   └── strava_client.py      # StravaAPI — HTTP client with retry + rate limiting
│   ├── auth/
│   │   └── oauth.py              # OAuth2Session — Strava authorization URL + code exchange
│   ├── config/
│   │   └── settings.py           # Config — dot-notation access to config/config.json
│   ├── exceptions/
│   │   └── errors.py             # Custom exception hierarchy
│   ├── filters/
│   │   └── filter_engine.py      # FilterCriteria + FilterEngine.apply()
│   ├── models/
│   │   ├── activity.py           # Activity model + from_strava_api()
│   │   ├── great_circle.py       # SLERP great-circle arc for connecting segments
│   │   └── project.py            # Project, ProjectItem, ConnectingSegment models
│   └── project/
│       ├── project_io.py         # ProjectIO — load/save/new/to_dict for .gettracks files
│       └── project_repo.py       # ProjectRepo — DB-backed CRUD for projects + activities
│
├── flutter_client/               # Flutter frontend (web / Android / iOS)
│   ├── lib/
│   │   ├── main.dart             # App entry point + provider setup
│   │   └── src/
│   │       ├── api/
│   │       │   └── client.dart   # ApiClient — HTTP + auth headers
│   │       ├── auth/
│   │       │   ├── auth_notifier.dart
│   │       │   ├── auth_service.dart
│   │       │   ├── login_screen.dart
│   │       │   └── register_screen.dart
│   │       ├── core/
│   │       │   └── app_router.dart   # go_router routes + auth guard
│   │       ├── map/              # Shared map utilities + location picker
│   │       ├── projects/
│   │       │   ├── app_screen.dart           # Main project screen (map + panel)
│   │       │   ├── project_notifier.dart     # Project state + CRUD methods
│   │       │   ├── project_service.dart      # API calls for project data
│   │       │   ├── projects_notifier.dart    # Project list state
│   │       │   ├── projects_screen.dart      # Project picker screen
│   │       │   ├── projects_service.dart     # API calls for project list
│   │       │   ├── segment_dialog.dart       # Add/edit connecting segment dialog
│   │       │   ├── strava_import_notifier.dart
│   │       │   └── strava_import_screen.dart # Strava activity browser + import
│   │       ├── settings/         # Settings screen
│   │       └── shared/           # Shared widgets
│   └── pubspec.yaml
│
├── alembic/                      # Database migrations
│   └── versions/
│
├── scripts/
│   └── migrate_to_db.py          # One-shot migration: .gettracks files → SQLite
│
├── config/
│   ├── config.example.json       # Template — copy to config.json and fill in credentials
│   └── config.json               # Gitignored — Strava + Google credentials
│
├── data/                         # Gitignored — runtime data
│   └── users/{user_id}/
│       └── projects/             # Per-user .gettracks project files
│
├── docs/
│   ├── architecture.md           # System architecture overview
│   ├── DEVELOPMENT_PLAN.md       # Feature roadmap
│   └── features.md               # Implemented features reference
│
├── tests/                        # Python test suite (pytest)
│
├── alembic.ini                   # Alembic configuration
├── docker-compose.yml            # Docker Compose for self-hosting
├── Dockerfile                    # Container image definition (FastAPI + uvicorn)
├── launch.bat                    # Windows dev launcher (FastAPI + Flutter)
├── requirements-web.txt          # Python dependencies
├── PROJECT_STRUCTURE.md          # This file
└── README.md                     # Getting started guide
```

## Key Concepts

### Data Storage

Project files are stored as `.gettracks` JSON files under `data/users/{user_id}/projects/`. Each file contains:
- Ordered `items` list (activities + connecting segments)
- `activities` dict keyed by Strava activity ID
- Per-activity `elevation_profile` as `[[dist_km, elev_m], ...]`

User accounts, Strava tokens, and project metadata are stored in SQLite via SQLModel. The database file defaults to `viewtripweb.db` (overridden by the `DATABASE_URL` environment variable).

### Auth Flow

1. User logs in via Google (`POST /api/auth/google`) or local email/password (`POST /api/auth/token`)
2. Server verifies credentials → creates/fetches `UserInfo` row → returns signed JWT
3. Flutter stores JWT in `SharedPreferences` and sends it as `Authorization: Bearer` on every API call
4. Strava OAuth: Flutter opens browser → user authorises → callback stores `StravaToken` row; the user's JWT is passed as the OAuth `state` param so the stateless callback can resolve the user

### GeoJSON Generation

`GET /api/geo/project` reads the project file and produces a GeoJSON FeatureCollection:
- Activity tracks: decoded from `summary_polyline` (Google encoded polyline via `polyline` lib) → `[[lon, lat], ...]`
- Fallback: straight line from `start_latlng` → `end_latlng` when no polyline
- Connecting segments: SLERP great-circle arc via `great_circle_points()`
- Coordinates in `[lon, lat]` order (GeoJSON standard)

### Database Schema

Managed by SQLModel + Alembic:

```
localuser       — username, bcrypt password hash, enabled flag
userinfo        — id, local_auth_id (FK), google_sub, email, display_name, avatar_url, auth_provider
stravatoken     — user_info_id (FK), access_token, refresh_token, expires_at
dbproject       — user_info_id (FK), name, created_at
dbactivity      — user_info_id (FK), strava_id, data (JSON)
dbprojectitem   — project_id (FK), position, item_type, activity_id, segment (JSON)
dbstravacache   — user_info_id (FK), last_sync, data (JSON)
```
