"""Project picker — shown after login before entering the main app."""
import reflex as rx

from app.state import ProjectPickerState
from app.components.layout import page_shell


def saved_project_row(entry: dict) -> rx.Component:
    return rx.hstack(
        rx.icon("folder-open", size=16, color=rx.color("orange", 9), flex_shrink="0"),
        rx.text(entry["name"], size="2", weight="medium", flex="1"),
        rx.button(
            "Open",
            size="1",
            color_scheme="orange",
            variant="soft",
            on_click=ProjectPickerState.open_saved(entry["path"]),
        ),
        width="100%",
        align="center",
        padding_y="2",
        padding_x="3",
        border_radius="var(--radius-3)",
        _hover={"background": rx.color("gray", 3)},
    )


def page() -> rx.Component:
    return page_shell(
        rx.flex(
            # ── Page header ────────────────────────────────────────────
            rx.vstack(
                rx.heading("Welcome back", size="6", weight="bold"),
                rx.text(
                    "What would you like to work on?",
                    size="3",
                    color=rx.color("gray", 10),
                ),
                spacing="1",
                align="center",
                width="100%",
                padding_y="6",
            ),
            # ── Three option cards ─────────────────────────────────────
            rx.flex(
                # Card 1 — Create new project
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.box(
                                rx.icon("circle-plus", size=28, color=rx.color("orange", 9)),
                                padding="3",
                                border_radius="var(--radius-3)",
                                background=rx.color("orange", 3),
                            ),
                            rx.vstack(
                                rx.text("New project", size="3", weight="bold"),
                                rx.text(
                                    "Start from scratch",
                                    size="2",
                                    color=rx.color("gray", 10),
                                ),
                                spacing="0",
                                align="start",
                            ),
                            spacing="3",
                            align="center",
                            width="100%",
                        ),
                        rx.separator(width="100%", my="2"),
                        rx.hstack(
                            rx.input(
                                placeholder="Project name…",
                                value=ProjectPickerState.new_project_name,
                                on_change=ProjectPickerState.set_new_project_name,
                                size="2",
                                flex="1",
                            ),
                            rx.button(
                                "Create",
                                on_click=ProjectPickerState.create_project,
                                color_scheme="orange",
                                size="2",
                            ),
                            width="100%",
                            spacing="2",
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    width="100%",
                    padding="5",
                ),
                # Card 2 — Open saved project
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.box(
                                rx.icon("folder", size=28, color=rx.color("blue", 9)),
                                padding="3",
                                border_radius="var(--radius-3)",
                                background=rx.color("blue", 3),
                            ),
                            rx.vstack(
                                rx.text("Saved projects", size="3", weight="bold"),
                                rx.text(
                                    "Resume previous work",
                                    size="2",
                                    color=rx.color("gray", 10),
                                ),
                                spacing="0",
                                align="start",
                            ),
                            spacing="3",
                            align="center",
                            width="100%",
                        ),
                        rx.separator(width="100%", my="2"),
                        rx.cond(
                            ProjectPickerState.saved_projects.length() == 0,
                            rx.center(
                                rx.vstack(
                                    rx.icon("inbox", size=24, color=rx.color("gray", 7)),
                                    rx.text(
                                        "No saved projects yet",
                                        size="2",
                                        color=rx.color("gray", 9),
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                padding_y="4",
                                width="100%",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    ProjectPickerState.saved_projects,
                                    saved_project_row,
                                ),
                                width="100%",
                                spacing="1",
                                max_height="200px",
                                overflow_y="auto",
                            ),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    width="100%",
                    padding="5",
                ),
                # Card 3 — Import GetTracks file
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.box(
                                rx.icon("upload", size=28, color=rx.color("green", 9)),
                                padding="3",
                                border_radius="var(--radius-3)",
                                background=rx.color("green", 3),
                            ),
                            rx.vstack(
                                rx.text("Import file", size="3", weight="bold"),
                                rx.text(
                                    "From GetTracks desktop",
                                    size="2",
                                    color=rx.color("gray", 10),
                                ),
                                spacing="0",
                                align="start",
                            ),
                            spacing="3",
                            align="center",
                            width="100%",
                        ),
                        rx.separator(width="100%", my="2"),
                        rx.upload(
                            rx.vstack(
                                rx.icon(
                                    "file-up",
                                    size=32,
                                    color=rx.color("gray", 7),
                                ),
                                rx.text(
                                    "Drop a .gettracks file here",
                                    size="2",
                                    color=rx.color("gray", 9),
                                    text_align="center",
                                ),
                                rx.text(
                                    "or click to browse",
                                    size="1",
                                    color=rx.color("gray", 8),
                                ),
                                spacing="2",
                                align="center",
                            ),
                            id="gettracks_upload",
                            accept={".gettracks": "application/json"},
                            max_files=1,
                            on_drop=ProjectPickerState.handle_upload(
                                rx.upload_files(upload_id="gettracks_upload")
                            ),
                            border=f"2px dashed {rx.color('gray', 5)}",
                            border_radius="var(--radius-3)",
                            padding="6",
                            width="100%",
                            cursor="pointer",
                            _hover={"border_color": rx.color("green", 7)},
                        ),
                        rx.cond(
                            ProjectPickerState.picker_error != "",
                            rx.callout(
                                ProjectPickerState.picker_error,
                                icon="triangle_alert",
                                color_scheme="red",
                                size="1",
                                width="100%",
                            ),
                            rx.fragment(),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    width="100%",
                    padding="5",
                ),
                direction="column",
                gap="4",
                width="100%",
                max_width="560px",
                margin="0 auto",
                padding_x="4",
                padding_bottom="8",
            ),
            direction="column",
            align="center",
            width="100%",
        ),
        on_mount=ProjectPickerState.on_load,
    )
