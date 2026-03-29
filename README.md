# ViewTripWeb

> Build multi-sport GPS journey files from your Strava activities — with connecting transport segments, elevation profiles, and one-click GPX export.

A self-hostable web application. Authenticate with Google or email/password, connect Strava, and assemble your trips from activities with flight/train/bus/boat connecting segments.

**Current release: v0.8.2** · Self-hosted via Docker · Flutter web/mobile frontend + FastAPI backend

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Flutter Web / Android / iOS |
| Backend | FastAPI · Python 3.11 |
| Database | SQLite via SQLModel / Alembic |
| Auth | Google OAuth + local email/password · JWT (PyJWT) |
| Strava | OAuth 2.0 · per-user token storage in DB |
| Maps | flutter_map (OpenStreetMap) |

---

## Quick Start (Docker)

```bash
# 1. Create your config
mkdir -p config
cp config/config.example.json config/config.json
# Edit config.json — add your Strava + Google credentials

# 2. Run
docker compose up -d
```

The API is available at `http://localhost:8000`. Point the Flutter app at that origin.

---

## Development Setup

### Backend

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements-web.txt
alembic upgrade head
uvicorn api.router:app --host 0.0.0.0 --port 8000 --reload
```

Backend API available at `http://localhost:8000/api/...`.

### Flutter Frontend

```bash
cd flutter_client
flutter pub get
flutter run -d chrome --web-port 5500
```

Or use `launch.bat` (Windows) which starts both together.

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

---

## API Reference

### Auth

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/auth/token` | Email + password login → JWT |
| POST | `/api/auth/register` | Create local account → JWT |
| POST | `/api/auth/google` | Google id_token → JWT |
| GET | `/api/auth/me` | Current user profile |
| PUT | `/api/auth/me` | Update display name |
| POST | `/api/auth/change-password` | Change password (local accounts) |
| DELETE | `/api/auth/me` | Delete account + all data |

### Projects

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

### Geo / Strava

| Method | Endpoint | Description |
|---|---|---|
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
