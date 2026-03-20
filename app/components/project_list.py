"""Ordered project item list component."""
import reflex as rx

from app.state import ProjectState


def project_item(name: str, idx: int) -> rx.Component:
    return rx.hstack(
        rx.icon("grip-vertical", color=rx.color("gray", 8), size=14, flex_shrink="0"),
        rx.text(name, size="2", flex="1", weight="medium"),
        rx.icon_button(
            rx.icon("x", size=12),
            variant="ghost",
            size="1",
            color_scheme="red",
            on_click=ProjectState.remove_item(idx),
        ),
        width="100%",
        padding_x="2",
        padding_y="2",
        border_radius="var(--radius-3)",
        align="center",
        _hover={"background": rx.color("gray", 3)},
        cursor="default",
    )


def project_list() -> rx.Component:
    return rx.cond(
        ProjectState.item_names.length() == 0,
        rx.center(
            rx.vstack(
                rx.icon("list-x", size=28, color=rx.color("gray", 7)),
                rx.text(
                    "No activities yet",
                    size="2",
                    color=rx.color("gray", 9),
                    text_align="center",
                ),
                rx.text(
                    "Import from Strava or add a transport segment.",
                    size="1",
                    color=rx.color("gray", 8),
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            padding_y="6",
            width="100%",
        ),
        rx.vstack(
            rx.foreach(
                ProjectState.item_names,
                lambda name, idx: project_item(name, idx),
            ),
            width="100%",
            spacing="1",
        ),
    )
