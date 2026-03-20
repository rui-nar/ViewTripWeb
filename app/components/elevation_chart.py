"""Elevation chart component using Reflex recharts with theme-aware colours."""
import reflex as rx


# Placeholder — will be replaced by real elevation data from ProjectState
_sample_data = [{"distance": 0, "elevation": 0}]


def elevation_chart() -> rx.Component:
    return rx.recharts.area_chart(
        rx.recharts.area(
            data_key="elevation",
            stroke=rx.color("orange", 9),
            fill=rx.color("orange", 3),
            stroke_width=2,
        ),
        rx.recharts.x_axis(
            data_key="distance",
            label={"value": "km", "position": "insideBottomRight", "offset": -5},
            tick={"fontSize": 11},
        ),
        rx.recharts.y_axis(
            label={"value": "m", "angle": -90, "position": "insideLeft", "offset": 10},
            tick={"fontSize": 11},
        ),
        rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=rx.color("gray", 4)),
        rx.recharts.graphing_tooltip(
            content_style={
                "background": rx.color("gray", 1),
                "border": f"1px solid {rx.color('gray', 4)}",
                "border_radius": "6px",
                "font_size": "12px",
            }
        ),
        data=_sample_data,
        width="100%",
        height=180,
    )
