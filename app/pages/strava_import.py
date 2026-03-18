"""Strava activity import page."""
import reflex as rx
from app.state import StravaState, ProjectState


def activity_row(activity: dict) -> rx.Component:
    return rx.hstack(
        rx.checkbox(),
        rx.vstack(
            rx.text(activity["name"], weight="bold"),
            rx.text(f"{activity['type']} · {activity['date']}", size="1", color="gray"),
            spacing="0",
        ),
        width="100%",
        padding_y="2",
        border_bottom="1px solid #f0f0f0",
    )


def page() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.link(rx.button("← Back", variant="ghost"), href="/"),
            rx.heading("Import from Strava", size="5"),
            rx.spacer(),
            rx.button(
                "Sync activities",
                on_click=StravaState.fetch_activities,
                loading=StravaState.is_loading,
                color_scheme="orange",
            ),
            width="100%",
            padding="4",
        ),
        rx.cond(
            StravaState.error_message != "",
            rx.callout(StravaState.error_message, color_scheme="red"),
            rx.fragment(),
        ),
        rx.cond(
            StravaState.is_loading,
            rx.spinner(size="3"),
            rx.vstack(
                rx.foreach(StravaState.activities, activity_row),
                width="100%",
                padding_x="4",
            ),
        ),
        spacing="0",
        on_mount=StravaState.on_load,
    )
