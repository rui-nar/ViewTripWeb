"""Jinja-rendered email bodies (issue #113).

Templates live as plain files under ``templates/`` — adding a new email
(verification, notifications, ...) is a new pair of files here plus a small
render function, no changes to the service layer.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# HTML templates must autoescape (user-controlled strings like project/owner
# names land in markup); the text counterpart must NOT — escaping would
# corrupt a plain-text body (e.g. "&" becoming "&amp;").
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=lambda name: name is not None and name.endswith(".html.jinja2"),
)


def render_invite_email(
    *, project_name: str, owner_name: str, role: str, join_url: str
) -> tuple[str, str]:
    """Render the travel-companion invite email. Returns (text_body, html_body)."""
    ctx = {
        "project_name": project_name,
        "owner_name": owner_name,
        "role": role,
        "join_url": join_url,
    }
    text_body = _env.get_template("invite.txt.jinja2").render(ctx)
    html_body = _env.get_template("invite.html.jinja2").render(ctx)
    return text_body, html_body
