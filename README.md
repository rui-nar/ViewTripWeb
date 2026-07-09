# ViewTripWeb

> Build multi-sport GPS journey files from your Strava (and Polarsteps) activities — with connecting transport segments, memories, journals, statistics, sharing, and one-click GPX export.

A self-hostable web application. Authenticate with Google or email/password, connect Strava and/or Polarsteps, and assemble your trips from activities with flight/train/bus/boat connecting segments. Annotate days with memories (photos, text, likes & comments) and journals, view rich statistics, and share a read-only public link to social media.

Self-hosted via Docker · Flutter web/mobile frontend + FastAPI backend. The running version is exposed at `/api/version` and tagged on the published image (set from the git tag at build time — never hardcoded).

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Flutter Web / Android / iOS |
| Backend | FastAPI · Python 3.11 |
| Database | SQLite via SQLModel / Alembic |
| Scheduling | APScheduler (daily DB backup at 02:00 UTC) |
| Auth | Google OAuth + local email/password · JWT (PyJWT) |
| Strava | OAuth 2.0 · per-user token storage in DB |
| Polarsteps | per-user token storage · trip/step import |
| Maps | flutter_map · Mapbox / Esri raster + vector tiles |
| Routing | OSM Overpass (rail/ferry/bus geometry) · HAFAS / digitraffic (train schedules) |
| Translation | Google Translate v2 (optional, memory translations) |

---

## Quick Start (Docker)

CI publishes the image to `ghcr.io/rui-nar/viewtripweb`. Provide your own
`docker-compose.yml` (not committed — it carries host-specific volume paths and
env) referencing that image, or build locally from the bundled `Dockerfile`.

```bash
# 1. Create your config
mkdir -p config
cp config/config.example.json config/config.json
# Edit config.json — add your Strava + Google credentials

# 2. Run (with your docker-compose.yml present)
docker compose up -d
```

The API (and the bundled Flutter web build, when present) is served at `http://localhost:8000`.
Interactive API docs: `http://localhost:8000/docs` (Swagger) and `http://localhost:8000/scalar` (Scalar).

Database migrations run automatically on startup (`alembic upgrade head`).

---

## Development Setup

### Backend

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
alembic upgrade head
uvicorn api.router:app --host 0.0.0.0 --port 8000 --reload
```

Backend API available at `http://localhost:8000/api/...`.

### Flutter Frontend

```bash
cd flutter_client
flutter pub get
flutter run -d chrome --web-port 5500 \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=MAPBOX_TOKEN=YOUR_MAPBOX_PUBLIC_TOKEN
```

Windows helper scripts: `dev-client.ps1` (Flutter client), `deploy.ps1` (build
+ push image + deploy to NAS), `bump_version_and_release.ps1` (tag a release).

---

## Configuration

`config/config.json`:
```json
{
  "strava": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "http://localhost:8000/api/strava/callback"
  },
  "google": {
    "client_id": "YOUR_GOOGLE_CLIENT_ID"
  }
}
```

- Register a Strava application at <https://www.strava.com/settings/api>. Set the **Authorization Callback Domain** to your server's hostname.
- Register a Google OAuth app at <https://console.developers.google.com>. Add your origin to the allowed origins.

### Environment variables

These are read by the backend at **runtime** (`os.getenv`) — a value passed to
`docker build` or `flutter build` does **not** reach the running server. Copy
[`.env.example`](.env.example) to `.env` and fill it in.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL for the DB (defaults to local `viewtripweb.db`) |
| `GOOGLE_TRANSLATE_API_KEY` | Enables memory translation endpoints (optional) |
| `GOOGLE_CLIENT_ID` | Google OAuth client id; takes priority over `config.json` (optional) |
| `APP_VERSION` | Running version; set automatically from the git tag at image build |

**Local dev:** export the vars before launching (`export $(grep -v '^#' .env | xargs)`),
or use `dev.ps1` / `dev-server.ps1`, which inject them for you.

**Docker / NAS:** load them into the container at runtime via your
`docker-compose.yml` — either an `environment:` block or `env_file: .env` — then
`docker compose up -d` to recreate the container so it picks up the values
(a plain `restart` does not apply env changes). Do **not** bake secrets into the
image with a Dockerfile `ENV`; the published image is public.

### Flutter build-time defines (`--dart-define`)

| Define | Purpose |
|---|---|
| `API_BASE_URL` | Backend origin; empty = same-origin (production) |
| `MAPBOX_TOKEN` | Mapbox public token for map tiles |
| `APP_VERSION` | Version string shown in the app |

---

## Features

- **Projects** — assemble trips from Strava/Polarsteps activities; reorder, sort chronologically, add flight/train/bus/boat connecting segments with real-world route geometry resolved from OSM/HAFAS.
- **Memories** — photo + text annotations per day, with likes, threaded comments, and optional translation.
- **Journals** — private day notes with photos.
- **Encounters** — a per-project directory of people you meet (name, social links, nationalities, residence city, avatar) and where/when you met them, shown inline on their day and as owner-only map pins. People and encounters are never included in shared views.
- **Statistics** — distance/elevation/time totals, per-mode and per-tag breakdowns, ride time-series charts.
- **Sharing** — read-only public links (with or without memories); social-media composer that posts a memory's photos, a trip map image, and a durable deep link via the OS share sheet / WhatsApp / Facebook.
- **Export** — GPX, `.viewtrip` (JSON), or ZIP (`.viewtrip` + photos).
- **Backups** — automatic daily SQLite backup (30-day retention) with user-initiated restore from settings.

---

## API Reference

The **authoritative, always-current** reference is the interactive OpenAPI UI:

- Swagger UI — `/docs`
- Scalar — `/scalar`
- Raw schema — `/openapi.json`

Routes are grouped by tag (router prefix):

| Tag | Prefix | Covers |
|---|---|---|
| `auth` | `/api/auth` | login (`/token`), register, Google login, profile, change/delete account |
| `projects` | `/api/projects` | project + item + segment CRUD, import/export, stats, day-meta, track style, share-token management, async route resolution |
| `geo` | `/api/geo` | full + low-res GeoJSON FeatureCollections for the map |
| `memories` | `/api/memories` | memory CRUD, photos, comments, likes, translations |
| `journal` | `/api/journal` | journal entry CRUD + photos |
| `share` | `/api/share` | public read-only project access, tiles, shared-memory comments/likes |
| `strava` | `/api/strava` | OAuth connect/callback/status, activity browsing, project sync |
| `polarsteps` | `/api/polarsteps` | connect/disconnect, trip + step listing |
| `backup` | `/api/backup` | list + restore database backups |

---

## Project Structure

See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for the full directory layout.

---

## License

MIT
