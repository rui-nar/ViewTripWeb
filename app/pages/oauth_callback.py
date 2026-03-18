"""OAuth callback page — receives Strava auth code."""
import reflex as rx
from app.state import StravaState


def page() -> rx.Component:
    code = rx.State.router.page.params.get("code", "")
    return rx.vstack(
        rx.spinner(size="3"),
        rx.text("Completing Strava authentication…"),
        on_mount=StravaState.handle_callback(code),
    )
