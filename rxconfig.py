import reflex as rx

config = rx.Config(
    app_name="app",
    frontend_port=3000,
    backend_port=8000,
    db_url="sqlite:///viewtripweb.db",
)
