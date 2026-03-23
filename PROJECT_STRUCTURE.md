# ViewTripWeb — Project Structure

## Directory Layout

```
ViewTripWeb/
│
├── api/                          # FastAPI route handlers
│   ├── auth.py                   # Google auth endpoints
│   ├── deps.py                   # JWT dependency (get_current_user)
│   ├── geo.py                    # GET /api/geo/project — GeoJSON builder
│   ├── projects.py               # Projects + items + segments CRUD
│   ├── router.py                 # Mounts all routers onto the FastAPI app
│   └── strava.py                 # Strava OAuth + activity sync
│
├── app/                          # Reflex web app (admin / auth scaffold)
│   ├── app.py                    # Reflex app entry point
│   ├── api/                      # Legacy Reflex API routes
│   ├── auth/                     # Google OAuth state (Reflex)
│   ├── components/               # Reflex UI components
│   ├── models/
│   │   └── user.py               # UserInfo + StravaToken SQLModel tables
│   └── pages/                    # Reflex pages (login, project picker, etc.)
│
├── src/                          # Core business logic (shared by API and tests)
│   ├── api/
│   │   └── strava_client.py      # StravaAPI — HTTP client with retry + rate limiting
│   ├── auth/
│   │   ├── oauth.py              # OAuth2Session — Strava OAuth flow
│   │   └── token_store.py        # Token persistence (file-based, desktop legacy)
│   ├── config/
│   │   └── settings.py           # Config — dot-notation access to config.json
│   ├── exceptions/
│   │   └── errors.py             # Custom exception hierarchy
│   ├── filters/
│   │   └── filter_engine.py      # FilterCriteria + FilterEngine.apply()
│   ├── models/
│   │   ├── activity.py           # Activity model + from_strava_api()
│   │   ├── great_circle.py       # SLERP great-circle arc for connecting segments
│   │   └── project.py            # Project, ProjectItem, ConnectingSegment models
│   ├── project/
│   │   └── project_io.py         # ProjectIO — load/save/new/to_dict for .gettracks files
│   └── utils/
│       └── logging.py            # Logging setup
│
├── flutter_client/               # Flutter web frontend
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
│   │       ├── map/              # Shared map utilities
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
│   │       └── shared/           # Shared widgets
│   └── pubspec.yaml
│
├── alembic/                      # Database migrations
│   └── versions/
│       └── d19c0b0b1c1e_add_stravatoken_table.py
│
├── config/
│   ├── config.example.json       # Template — copy to config.json and fill in credentials
│   └── config.json               # Gitignored — Strava API credentials
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
├── Dockerfile                    # Container image definition
├── requirements-web.txt          # Python dependencies (web / production)
├── rxconfig.py                   # Reflex configuration
├── PROJECT_STRUCTURE.md          # This file
└── README.md                     # Getting started guide
```

## Key Concepts

### Data Storage

User project files are stored as `.gettracks` JSON files under `data/users/{user_id}/projects/`. Each file contains:
- Ordered `items` list (activities + connecting segments)
- `activities` dict keyed by Strava activity ID
- Per-activity `elevation_profile` as `[[dist_km, elev_m], ...]`

### Auth Flow

1. User logs in via Reflex Google OAuth → `UserInfo` row created in SQLite
2. Reflex session issues a JWT used as `Authorization: Bearer` on all Flutter API calls
3. Strava OAuth: Flutter opens browser → user authorises → callback stores `StravaToken` row in DB

### GeoJSON Generation

`GET /api/geo/project` reads the project file and produces a GeoJSON FeatureCollection:
- Activity tracks: decoded from `summary_polyline` (Google encoded polyline)
- Fallback: straight line from `start_latlng` → `end_latlng` when no polyline
- Connecting segments: SLERP great-circle arc via `great_circle_points()`
- Coordinates in `[lon, lat]` order (GeoJSON standard)
