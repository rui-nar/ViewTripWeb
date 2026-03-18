"""ViewTripWeb — Reflex entry point."""
import reflex as rx

from app.pages import index, strava_import, export, oauth_callback
from app.api.geo import geo_project, map_html


app = rx.App()
app.add_page(index.page, route="/")
app.add_page(strava_import.page, route="/import")
app.add_page(export.page, route="/export")
app.add_page(oauth_callback.page, route="/callback")

app.api.add_api_route("/api/geo/project", geo_project)
app.api.add_api_route("/api/geo/map", map_html)
