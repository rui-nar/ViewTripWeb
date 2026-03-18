"""Map component — Leaflet.js embedded via iframe with GeoJSON API."""
import reflex as rx


def map_view() -> rx.Component:
    """
    Embed a Leaflet map served from a static HTML template.
    The template fetches /api/geo/project and renders GeoJSON.
    """
    return rx.el.iframe(
        src="/api/geo/map",
        width="100%",
        height="400px",
        style={"border": "none", "border_radius": "8px"},
    )
