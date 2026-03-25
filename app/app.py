"""ViewTripWeb — Reflex entry point."""
import reflex as rx
from starlette.applications import Starlette
from starlette.routing import Route

import reflex_local_auth  # noqa: F401 — ensures local-auth models are registered

from app.pages import index, strava_import, export, oauth_callback
from app.pages import login, register, project_picker
from app.api.geo import map_html
from app.auth.state import AuthState
from api.router import api as rest_api  # Flutter / native-client REST API


def api_transformer(app):
    """Mount REST API and legacy geo routes alongside the Reflex ASGI app.

    Request routing:
        /api/*          → FastAPI (JWT auth, project CRUD, GeoJSON — used by Flutter)
        /api/geo/map    → Starlette legacy map HTML page (used by Reflex web only)
        everything else → Reflex ASGI app
    """
    legacy_geo_app = Starlette(routes=[
        Route("/api/geo/map", map_html),
    ])

    async def combined(scope, receive, send):
        path = scope.get("path", "")
        if path == "/api/geo/map":
            await legacy_geo_app(scope, receive, send)
        elif path.startswith("/api/"):
            await rest_api(scope, receive, send)
        else:
            await app(scope, receive, send)

    return combined


app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color="orange",
        gray_color="slate",
        radius="large",
        scaling="100%",
    ),
    api_transformer=api_transformer,
)

# ── Public routes ─────────────────────────────────────────────────────────────
app.add_page(login.page, route="/login")
app.add_page(register.page, route="/register")

# ── Protected routes — redirect to /login if not authenticated ────────────────
app.add_page(
    project_picker.page,
    route="/projects",
    on_load=AuthState.redir,
)
app.add_page(index.page, route="/", on_load=AuthState.redir)
app.add_page(strava_import.page, route="/import", on_load=AuthState.redir)
app.add_page(export.page, route="/export", on_load=AuthState.redir)
app.add_page(oauth_callback.page, route="/callback", on_load=AuthState.redir)
