"""Ordered project item list component."""
import reflex as rx
from app.state import ProjectState


def project_item(name: str, idx: int) -> rx.Component:
    return rx.hstack(
        rx.icon("grip-vertical", color="gray", size=14),
        rx.text(name, flex="1"),
        rx.icon_button(
            rx.icon("x", size=12),
            variant="ghost",
            size="1",
            color_scheme="red",
            on_click=ProjectState.remove_item(idx),
        ),
        width="100%",
        padding_y="1",
        padding_x="2",
        border_radius="4px",
        _hover={"background": "#f7f7f7"},
    )


def project_list() -> rx.Component:
    return rx.cond(
        ProjectState.item_names.length() == 0,
        rx.text("No items yet. Import activities or add a transport segment.", color="gray", size="2"),
        rx.vstack(
            rx.foreach(
                ProjectState.item_names,
                lambda name, idx: project_item(name, idx),
            ),
            width="100%",
            spacing="1",
        ),
    )
