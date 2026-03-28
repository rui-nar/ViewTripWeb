"""Shared layout: sticky navbar + page shell wrapper."""
import reflex as rx
import reflex_google_auth

from app.auth.state import AuthState
from app.auth.google import GoogleCallbackState
from app.state import StravaState


def navbar() -> rx.Component:
    return rx.box(
        rx.flex(
            # Brand
            rx.link(
                rx.hstack(
                    rx.icon("map-pin", color=rx.color("orange", 9), size=20),
                    rx.heading("ViewTripWeb", size="4", weight="bold"),
                    spacing="2",
                    align="center",
                ),
                href="/",
                _hover={"text_decoration": "none"},
            ),
            rx.spacer(),
            # Projects navigation
            rx.button(
                rx.icon("grid-2x2", size=14),
                "Projects",
                variant="ghost",
                size="2",
                gap="1",
                color_scheme="gray",
                on_click=rx.redirect("/projects"),
            ),
            # Strava connection badge
            rx.cond(
                StravaState.is_authenticated,
                rx.badge(
                    rx.icon("activity", size=12),
                    "Strava",
                    color_scheme="orange",
                    variant="soft",
                    gap="1",
                ),
                rx.fragment(),
            ),
            # Dark mode toggle
            rx.color_mode.button(variant="ghost", size="2"),
            # User section
            rx.cond(
                AuthState.is_authenticated,
                rx.hstack(
                    rx.cond(
                        AuthState.avatar_url != "",
                        rx.avatar(src=AuthState.avatar_url, size="2", radius="full"),
                        rx.avatar(
                            fallback=AuthState.display_name[:2].upper(),
                            size="2",
                            radius="full",
                            color_scheme="orange",
                        ),
                    ),
                    rx.text(AuthState.display_name, size="2", weight="medium"),
                    rx.button(
                        "Sign out",
                        variant="ghost",
                        size="2",
                        color_scheme="gray",
                        on_click=AuthState.logout,
                    ),
                    spacing="3",
                    align="center",
                ),
                rx.fragment(),
            ),
            align="center",
            width="100%",
            padding_x="5",
            padding_y="3",
            gap="3",
        ),
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        background=rx.color("gray", 1),
        position="sticky",
        top="0",
        z_index="100",
        width="100%",
    )


def page_shell(*children, on_mount=None) -> rx.Component:
    """Wrap page content with the navbar and Google OAuth provider context."""
    vstack_props = dict(
        spacing="0",
        min_height="100vh",
        background=rx.color("gray", 2),
        width="100%",
    )
    content = rx.vstack(
        navbar(),
        rx.box(*children, width="100%", flex="1"),
        **vstack_props,
    )
    if on_mount:
        content = rx.vstack(
            navbar(),
            rx.box(*children, width="100%", flex="1"),
            on_mount=on_mount,
            **vstack_props,
        )
    # Wrap in Google OAuth provider so Google login button works everywhere
    return reflex_google_auth.google_oauth_provider(content)
