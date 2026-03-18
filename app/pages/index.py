"""Main project view page."""
import reflex as rx
from app.state import ProjectState, StravaState
from app.components.project_list import project_list
from app.components.map_view import map_view
from app.components.elevation_chart import elevation_chart


def page() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("ViewTripWeb", size="6"),
            rx.spacer(),
            rx.cond(
                StravaState.is_authenticated,
                rx.badge("Strava connected", color_scheme="green"),
                rx.link(
                    rx.button("Connect Strava", color_scheme="orange"),
                    href=StravaState.auth_url,
                    is_external=True,
                    on_click=StravaState.start_oauth,
                ),
            ),
            width="100%",
            padding="4",
            border_bottom="1px solid #e2e8f0",
        ),
        rx.hstack(
            # Left: project item list
            rx.vstack(
                rx.hstack(
                    rx.heading(ProjectState.project_name, size="4"),
                    rx.cond(ProjectState.is_dirty, rx.badge("unsaved", color_scheme="yellow"), rx.fragment()),
                ),
                project_list(),
                rx.hstack(
                    rx.button("New project", on_click=lambda: ProjectState.new_project("My Trip"), size="2"),
                    rx.link(rx.button("Import Strava", size="2"), href="/import"),
                    rx.link(rx.button("Export GPX", size="2", color_scheme="green"), href="/export"),
                    spacing="2",
                ),
                width="320px",
                padding="4",
                border_right="1px solid #e2e8f0",
                height="calc(100vh - 64px)",
                overflow_y="auto",
            ),
            # Right: map + elevation
            rx.vstack(
                map_view(),
                elevation_chart(),
                flex="1",
                padding="4",
            ),
            width="100%",
            align="start",
        ),
        spacing="0",
        on_mount=StravaState.on_load,
    )
