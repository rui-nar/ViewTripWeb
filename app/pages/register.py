"""Registration page — username + password."""
import reflex as rx

from reflex_local_auth.pages.registration import register_form
from reflex_local_auth.local_auth import LocalAuthState

from app.pages.login import auth_shell


def page() -> rx.Component:
    return auth_shell(
        rx.cond(
            LocalAuthState.is_hydrated,
            rx.card(
                rx.vstack(
                    # Brand
                    rx.hstack(
                        rx.icon("map-pin", color=rx.color("orange", 9), size=24),
                        rx.heading("ViewTripWeb", size="6", weight="bold"),
                        spacing="2",
                        align="center",
                        justify="center",
                        width="100%",
                    ),
                    rx.text(
                        "Create your account",
                        size="2",
                        color=rx.color("gray", 10),
                        text_align="center",
                        width="100%",
                    ),
                    rx.separator(width="100%", my="2"),
                    register_form(),
                    rx.center(
                        rx.hstack(
                            rx.text("Already have an account?", size="2"),
                            rx.link(
                                "Sign in",
                                href="/login",
                                size="2",
                                color=rx.color("orange", 9),
                            ),
                            spacing="1",
                        ),
                        width="100%",
                    ),
                    spacing="4",
                    width="100%",
                ),
                width="420px",
                padding="8",
                style={"backdrop_filter": "blur(2px)"},
            ),
        ),
    )
