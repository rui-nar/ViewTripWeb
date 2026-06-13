# ViewTripWeb — Project Structure

## Directory Layout

```
ViewTripWeb/
│
├── api/                          # FastAPI route handlers (mounted in router.py)
│   ├── router.py                 # FastAPI app: mounts routers, lifespan, SPA fallback
│   ├── deps.py                   # JWT dependency (get_current_user, create_access_token)
│   ├── auth.py                   # Auth endpoints (local + Google → JWT)
│   ├── projects.py               # Projects, items, segments, import/export, stats, sharing
│   ├── geo.py                    # GeoJSON builders (full + low-res)
│   ├── memories.py               # Memory CRUD, photos, comments, likes, translations
│   ├── journal.py                # Journal entry CRUD + photos
│   ├── share.py                  # Public read-only share endpoints + tiles
│   ├── strava.py                 # Strava OAuth + activity browsing/sync
│   ├── polarsteps.py             # Polarsteps connect + trip/step listing
│   ├── backup.py                 # List/restore database backups
│   └── translations.py           # Google Translate helper (used by memory endpoints)
│
├── models/                       # SQLModel database models
│   ├── db.py                     # Engine + get_session() context manager
│   ├── project_db.py             # All project-domain tables (see Schema below)
│   └── user.py                   # LocalUser, UserInfo, StravaToken, PolarstepsToken
│
├── src/                          # Core business logic (shared by API and tests)
│   ├── api/
│   │   ├── strava_client.py      # StravaAPI — HTTP client with retry + rate limiting
│   │   └── polarsteps_client.py  # Polarsteps trip/step fetch client
│   ├── auth/                     # OAuth2 session, callback handler, token store
│   ├── backup/
│   │   └── backup_service.py     # SQLite online backup / restore / prune (30-day)
│   ├── cache/
│   │   └── activity_cache.py     # Per-user Strava activity cache
│   ├── config/settings.py        # Config — dot-notation access to config/config.json
│   ├── exceptions/errors.py      # Custom exception hierarchy
│   ├── filters/filter_engine.py  # FilterCriteria + FilterEngine.apply()
│   ├── gpx/processor.py          # GPX export
│   ├── models/                   # Domain models: activity, project, memory, journal,
│   │                             #   track, great_circle (SLERP arc for segments)
│   ├── project/
│   │   ├── project_io.py         # ProjectIO — (de)serialise .viewtrip JSON
│   │   └── project_repo.py       # ProjectRepo — DB-backed CRUD (optimistic locking)
│   ├── services/
│   │   ├── hafas_service.py      # Train schedules (DB/ÖBB/DSB/VR digitraffic)
│   │   └── overpass_service.py   # OSM rail/ferry/bus route geometry
│   └── utils/logging.py          # Logger setup
│
├── flutter_client/               # Flutter frontend (web / Android / iOS)
│   ├── lib/
│   │   ├── main.dart             # App entry point + provider setup
│   │   └── src/
│   │       ├── api/              # ApiClient — HTTP + auth headers
│   │       ├── auth/            # Login/register + auth state
│   │       ├── core/            # app_router.dart (go_router + auth guard)
│   │       ├── map/            # Shared map utilities + location picker
│   │       ├── projects/      # Main project screen, map panel, stats, memories,
│   │       │                  #   image export, social share dialog
│   │       ├── settings/      # Settings screen (incl. backup restore)
│   │       ├── share/        # Pure social-share units + platform edges
│   │       └── shared/       # Read-only shared-project view
│   └── pubspec.yaml
│
├── alembic/                      # Database migrations
│   └── versions/
│
├── scripts/                      # One-off scripts (migrate_to_db, icons, release, version)
├── config/
│   ├── config.example.json       # Template — copy to config.json and fill in credentials
│   └── config.json               # Gitignored — Strava + Google credentials
│
├── assets/                       # App icons / static assets
├── tests/                        # Python test suite (pytest)
│
├── alembic.ini                   # Alembic configuration
├── Dockerfile                    # Container image (FastAPI + uvicorn + bundled web build)
├── entrypoint.sh                 # Container entrypoint
├── requirements.txt              # Python dependencies
├── deploy.ps1                    # Gitignored — build + push image + deploy to NAS
├── PROJECT_STRUCTURE.md          # This file
└── README.md                     # Getting started guide
```

> `docker-compose.yml` is gitignored (host-specific paths + env); CI publishes
> the image to `ghcr.io/rui-nar/viewtripweb`.

## Key Concepts

### Data Storage

All data lives in **SQLite via SQLModel** (file defaults to `viewtripweb.db`,
overridable with `DATABASE_URL`). Migrations are managed by Alembic and run
automatically on startup (`alembic upgrade head` in the FastAPI lifespan).

Projects are persisted as relational rows (project + ordered items + activities
+ memories + journals + segments). The `.viewtrip` format (legacy `.gettracks`
still accepted on import) is the JSON serialisation used for import/export only,
produced by `ProjectIO`. Photos are stored on disk under the data volume,
referenced by UUID from the memory/journal rows.

A daily backup of the SQLite file is taken at 02:00 UTC (APScheduler), kept for
30 days, and restorable from the settings screen.

### Auth Flow

1. User logs in via Google (`POST /api/auth/google`) or local email/password (`POST /api/auth/token`)
2. Server verifies credentials → creates/fetches `UserInfo` row → returns signed JWT
3. Flutter stores the JWT and sends it as `Authorization: Bearer` on every API call
4. Strava/Polarsteps OAuth: the user's JWT is passed as the OAuth `state` param so the stateless callback can resolve the user, then a token row is stored

### GeoJSON & Route Resolution

`GET /api/geo/project` produces a GeoJSON FeatureCollection: activity tracks
decoded from `summary_polyline` (or a straight `start→end` fallback), and
connecting segments. Transport segments (train/ferry/bus) have their real-world
geometry resolved asynchronously via `hafas_service` (schedules) and
`overpass_service` (OSM rail/ferry/bus ways), falling back to a great-circle arc.

### Sharing

Read-only public links come in two flavours (`share_token`, with memories, and
`share_token_no_memories`). A memory can be deep-linked via
`/share/<token>?memory=<public_id>`, where `public_id` is a stable per-memory
UUID independent of the primary key, so links survive re-import.

### Database Schema (SQLModel + Alembic)

| Table | Purpose |
|---|---|
| `localuser` | Local account: username, bcrypt hash, enabled flag |
| `userinfo` | Identity: local/google link, email, display name, avatar, provider |
| `stravatoken` | Per-user Strava OAuth tokens |
| `polarstepstoken` | Per-user Polarsteps token |
| `project` | A trip: name, dates, filter/day-meta/stats/counters JSON, track style, share tokens, lock_version |
| `projectsyncmeta` | Per-project Strava/Polarsteps sync configuration + timestamps |
| `projectitem` | Ordered item (activity / segment / memory / journal) with position |
| `activity` | Cached Strava/GPX activity (geometry, elevation, inline fields) |
| `memory` | Day annotation: public_id, date, text, photos, geo, like/comment counts |
| `memory_comment` | Threaded comments on a memory |
| `memory_like` | Likes on a memory |
| `memory_translation` | Cached translations of a memory's text |
| `journalentry` | Private day note with photos |
| `sharevisit` | Visitor analytics for share links |
| `stravacache` | Per-user Strava activity-list cache |
