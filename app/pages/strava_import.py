"""Strava activity import page."""
import reflex as rx

from app.state import StravaState, ProjectState
from app.components.layout import page_shell


def activity_row(activity: dict) -> rx.Component:
    return rx.hstack(
        rx.checkbox(
            is_checked=StravaState.selected_ids.contains(activity["id"]),
            on_change=lambda _: StravaState.toggle_activity(activity["id"]),
            size="2",
        ),
        rx.vstack(
            rx.text(activity["name"], size="2", weight="medium"),
            rx.hstack(
                rx.badge(activity["type"], variant="soft", size="1", color_scheme="gray"),
                rx.text(activity["date"], size="1", color=rx.color("gray", 10)),
                spacing="2",
                align="center",
            ),
            spacing="1",
        ),
        width="100%",
        padding_y="3",
        padding_x="1",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        align="center",
        _hover={"background": rx.color("gray", 2)},
        border_radius="var(--radius-2)",
    )


def empty_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("cloud-download", size=40, color=rx.color("gray", 7)),
            rx.text("No activities yet", size="3", weight="medium", color=rx.color("gray", 10)),
            rx.text(
                "Click Sync to fetch your latest Strava activities.",
                size="2",
                color=rx.color("gray", 9),
                text_align="center",
            ),
            spacing="2",
            align="center",
        ),
        padding_y="12",
    )


def page() -> rx.Component:
    return page_shell(
        rx.flex(
            # ── Toolbar card ─────────────────────────────────────────────
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
                    rx.heading("Import from Strava", size="4"),
                    rx.spacer(),
                    rx.hstack(
                        rx.button(
                            rx.icon("refresh-cw", size=14),
                            "Sync",
                            on_click=StravaState.fetch_activities,
                            loading=StravaState.is_loading,
                            color_scheme="orange",
                            size="2",
                            gap="1",
                        ),
                        rx.button(
                            rx.icon("circle-plus", size=14),
                            "Add to Project",
                            on_click=StravaState.add_selected_to_project,
                            disabled=StravaState.selected_ids.length() == 0,
                            color_scheme="blue",
                            size="2",
                            gap="1",
                        ),
                        spacing="2",
                    ),
                    width="100%",
                    align="center",
                ),
                width="100%",
            ),
            # ── Error callout ────────────────────────────────────────────
            rx.cond(
                StravaState.error_message != "",
                rx.callout(
                    StravaState.error_message,
                    icon="triangle_alert",
                    color_scheme="red",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # ── Activity list card ───────────────────────────────────────
            rx.card(
                rx.cond(
                    StravaState.is_loading,
                    rx.center(rx.spinner(size="3"), padding_y="12"),
                    rx.cond(
                        StravaState.activities.length() == 0,
                        empty_state(),
                        rx.vstack(
                            rx.hstack(
                                rx.text(
                                    StravaState.selected_ids.length(),
                                    " selected",
                                    size="2",
                                    color=rx.color("gray", 10),
                                ),
                                width="100%",
                            ),
                            rx.foreach(StravaState.activities, activity_row),
                            width="100%",
                            spacing="0",
                        ),
                    ),
                ),
                width="100%",
            ),
            direction="column",
            gap="4",
            padding="4",
            max_width="800px",
            margin="0 auto",
            width="100%",
        ),
        on_mount=StravaState.on_load,
    )
