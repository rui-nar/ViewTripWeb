"""GPX preview and export page."""
import reflex as rx

from app.state import ExportState, ProjectState
from app.components.map_view import map_view
from app.components.layout import page_shell


def page() -> rx.Component:
    return page_shell(
        rx.flex(
            # ── Toolbar ──────────────────────────────────────────────────
            rx.card(
                rx.hstack(
                    rx.button(
                        rx.icon("arrow-left", size=14),
                        "Back",
                        variant="ghost",
                        size="2",
                        gap="1",
                        on_click=rx.redirect("/"),
                    ),
                    rx.heading("Export GPX", size="4"),
                    rx.spacer(),
                    rx.hstack(
                        rx.button(
                            rx.icon("file-down", size=14),
                            "Download GPX",
                            color_scheme="green",
                            size="2",
                            gap="1",
                            on_click=lambda: ExportState.export_gpx("/data/exports/export.gpx"),
                        ),
                        rx.cond(
                            ExportState.export_status != "",
                            rx.badge(
                                ExportState.export_status,
                                color_scheme="green",
                                variant="soft",
                            ),
                            rx.fragment(),
                        ),
                        spacing="3",
                        align="center",
                    ),
                    width="100%",
                    align="center",
                ),
                width="100%",
            ),
            # ── Map preview ──────────────────────────────────────────────
            rx.card(
                map_view(),
                padding="0",
                overflow="hidden",
                width="100%",
                style={"border_radius": "var(--radius-4)"},
            ),
            direction="column",
            gap="4",
            padding="4",
            width="100%",
        ),
    )
