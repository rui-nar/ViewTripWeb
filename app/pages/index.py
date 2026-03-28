"""Main project view page."""
import reflex as rx

from app.state import ProjectState, StravaState
from app.components.project_list import project_list
from app.components.map_view import map_view
from app.components.elevation_chart import elevation_chart
from app.components.layout import page_shell


def page() -> rx.Component:
    return page_shell(
        rx.flex(
            # ── Left sidebar ────────────────────────────────────────────
            rx.card(
                rx.vstack(
                    # Project header
                    rx.hstack(
                        rx.heading(
                            rx.cond(
                                ProjectState.project_name != "",
                                ProjectState.project_name,
                                "No project open",
                            ),
                            size="3",
                            weight="bold",
                        ),
                        rx.cond(
                            ProjectState.is_dirty,
                            rx.badge("unsaved", color_scheme="yellow", variant="soft", size="1"),
                            rx.fragment(),
                        ),
                        justify="between",
                        width="100%",
                        align="center",
                    ),
                    rx.separator(width="100%"),
                    # Activity list
                    project_list(),
                    rx.separator(width="100%"),
                    # Action buttons
                    rx.vstack(
                        rx.button(
                            rx.icon("plus", size=14),
                            "New project",
                            on_click=lambda: ProjectState.new_project("My Trip"),
                            width="100%",
                            variant="outline",
                            gap="1",
                        ),
                        rx.cond(
                            StravaState.is_authenticated,
                            rx.button(
                                rx.icon("download", size=14),
                                "Import from Strava",
                                width="100%",
                                color_scheme="orange",
                                gap="1",
                                on_click=rx.redirect("/import"),
                            ),
                            rx.button(
                                rx.icon("link", size=14),
                                "Connect Strava first",
                                width="100%",
                                variant="outline",
                                color_scheme="orange",
                                gap="1",
                                on_click=StravaState.start_oauth,
                            ),
                        ),
                        rx.button(
                            rx.icon("file-down", size=14),
                            "Export GPX",
                            width="100%",
                            color_scheme="green",
                            variant="soft",
                            gap="1",
                            on_click=rx.redirect("/export"),
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    spacing="4",
                    width="100%",
                    height="100%",
                ),
                width="300px",
                flex_shrink="0",
                height="calc(100vh - 57px)",
                overflow_y="auto",
                style={"position": "sticky", "top": "57px"},
            ),
            # ── Right panel ─────────────────────────────────────────────
            rx.vstack(
                # Map card
                rx.card(
                    map_view(),
                    padding="0",
                    overflow="hidden",
                    width="100%",
                    style={"border_radius": "var(--radius-4)"},
                ),
                # Elevation card
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.icon("trending-up", size=14, color=rx.color("gray", 10)),
                            rx.text(
                                "Elevation profile",
                                size="2",
                                weight="medium",
                                color=rx.color("gray", 11),
                            ),
                            spacing="1",
                            align="center",
                        ),
                        elevation_chart(),
                        spacing="3",
                        width="100%",
                    ),
                    width="100%",
                ),
                spacing="4",
                flex="1",
                min_width="0",
            ),
            gap="4",
            padding="4",
            align="start",
            width="100%",
        ),
        on_mount=StravaState.on_load,
    )
