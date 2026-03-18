"""GPX preview and export page."""
import reflex as rx
from app.state import ExportState, ProjectState
from app.components.map_view import map_view


def page() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.link(rx.button("← Back", variant="ghost"), href="/"),
            rx.heading("Export GPX", size="5"),
            width="100%",
            padding="4",
        ),
        map_view(),
        rx.hstack(
            rx.button(
                "Download GPX",
                color_scheme="green",
                on_click=lambda: ExportState.export_gpx("/data/exports/export.gpx"),
            ),
            rx.cond(
                ExportState.export_status != "",
                rx.text(ExportState.export_status, color="green"),
                rx.fragment(),
            ),
            padding="4",
        ),
        spacing="0",
    )
