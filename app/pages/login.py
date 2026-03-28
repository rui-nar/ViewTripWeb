"""Login page — email/password + Google sign-in."""
import reflex as rx
import reflex_google_auth

from reflex_local_auth.pages.login import login_form
from reflex_local_auth.login import LoginState
from app.auth.google import GoogleCallbackState


# Splash SVG — faithfully reproduced from GetTracks src/gui/splash.py
_BG_IMAGE = "/splash.svg"


def auth_shell(*content) -> rx.Component:
    """Full-page wrapper with the GetTracks splash as a tiled/cover background."""
    return rx.box(
        # Background: GetTracks splash SVG, tiled horizontally, faded
        rx.box(
            style={
                "position": "absolute",
                "inset": "0",
                "background_image": f"url('{_BG_IMAGE}')",
                "background_size": "cover",
                "background_position": "center",
                "opacity": "0.55",
                "transform": "scale(1.04)",  # avoid blur edge bleed
                "filter": "blur(1px)",
            }
        ),
        # Additional dark tint so card text is legible
        rx.box(
            style={
                "position": "absolute",
                "inset": "0",
                "background": "rgba(8, 14, 22, 0.60)",
            }
        ),
        # Centered card content
        rx.center(
            *content,
            style={"position": "relative", "z_index": "1", "width": "100%"},
            min_height="100vh",
        ),
        style={
            "position": "relative",
            "min_height": "100vh",
            "overflow": "hidden",
            "background": "#0d1b2a",  # same as splash BG_TOP — shows while SVG loads
        },
    )


def google_signin_button() -> rx.Component:
    return rx.center(
        rx.button(
            rx.image(
                src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg",
                width="18px",
                height="18px",
            ),
            rx.text("Continue with Google", size="2"),
            on_click=reflex_google_auth.handle_google_login(
                on_success=GoogleCallbackState.on_success
            ),
            variant="outline",
            width="100%",
            gap="2",
        ),
        width="100%",
    )


def page() -> rx.Component:
    return reflex_google_auth.google_oauth_provider(
        auth_shell(
            rx.cond(
                LoginState.is_hydrated,
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
                            "Sign in to continue",
                            size="2",
                            color=rx.color("gray", 10),
                            text_align="center",
                            width="100%",
                        ),
                        rx.separator(width="100%", my="2"),
                        login_form(),
                        rx.separator(width="100%", my="2"),
                        google_signin_button(),
                        rx.center(
                            rx.hstack(
                                rx.text("No account?", size="2"),
                                rx.link(
                                    "Create one",
                                    href="/register",
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
    )
