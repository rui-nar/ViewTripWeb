# ViewTripWeb

> Build multi-sport GPS journey files from your Strava activities — with connecting transport segments, elevation profiles, and one-click GPX export.

A self-hostable web application. Authenticate with Google, connect Strava, and assemble your trips from activities with flight/train/bus/boat connecting segments.

**Current release: v0.7.0** · Self-hosted via Docker · Flutter web frontend + Python/Reflex backend

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Flutter Web |
| Backend | Reflex (FastAPI) · Python 3.11 |
| Database | SQLite via SQLModel / Alembic |
| Auth | Google OAuth (Reflex) + JWT |
| Strava | OAuth 2.0 · per-user token storage in DB |
| Maps | flutter_map (OpenStreetMap) |

---

## Quick Start (Docker)

```bash
# 1. Create your config
mkdir -p config
cp config/config.example.json config/config.json
# Edit config.json — add your Strava client_id and client_secret

# 2. Run
docker compose up -d
```

The Flutter app is served at `http://localhost:5500` and the backend API at `http://localhost:8000`.

---

## Development Setup

### Backend

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements-web.txt
reflex db migrate
reflex run
```

Backend API available at `http://localhost:8000/api/...`.

### Flutter Frontend

```bash
cd flutter_client
flutter pub get
flutter run -d chrome --web-port 5500
```

---

## Configuration

`config/config.json`:
```json
{
  "strava": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "http://localhost:8000/api/strava/callback"
  }
}
```

Register a Strava application at <https://www.strava.com/settings/api>.
Set the **Authorization Callback Domain** to your server's hostname.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/projects/` | List projects |
| POST | `/api/projects/` | Create project |
| GET | `/api/projects/{name}` | Get project data |
| DELETE | `/api/projects/{name}` | Delete project |
| POST | `/api/projects/import` | Upload `.gettracks` file |
| POST | `/api/projects/{name}/activities` | Add activities to project |
| DELETE | `/api/projects/{name}/items/{index}` | Remove item at index |
| PUT | `/api/projects/{name}/items/reorder` | Reorder items |
| POST | `/api/projects/{name}/segments` | Create connecting segment |
| PUT | `/api/projects/{name}/segments/{id}` | Update segment |
| DELETE | `/api/projects/{name}/segments/{id}` | Delete segment |
| GET | `/api/geo/project?name=` | GeoJSON FeatureCollection for map |
| GET | `/api/strava/connect` | Get Strava OAuth URL |
| GET | `/api/strava/callback` | OAuth redirect handler |
| GET | `/api/strava/status` | Strava connection status |
| DELETE | `/api/strava/disconnect` | Remove Strava token |
| GET | `/api/strava/activities` | Browse Strava activities (with filters) |
| POST | `/api/projects/{name}/strava/sync` | Sync all Strava activities to project |

---

## Project Structure

See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for the full directory layout.

---

## License

MIT
