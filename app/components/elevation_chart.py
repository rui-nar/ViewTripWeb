"""Elevation chart component using Reflex recharts."""
import reflex as rx


# Placeholder state var — will be populated from project elevation profiles
_sample_data = [{"distance": 0, "elevation": 0}]


def elevation_chart() -> rx.Component:
    return rx.recharts.area_chart(
        rx.recharts.area(
            data_key="elevation",
            stroke="#f97316",
            fill="#fed7aa",
        ),
        rx.recharts.x_axis(data_key="distance", label={"value": "km", "position": "insideBottomRight"}),
        rx.recharts.y_axis(label={"value": "m", "angle": -90, "position": "insideLeft"}),
        rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
        rx.recharts.graphing_tooltip(),
        data=_sample_data,
        width="100%",
        height=200,
    )
