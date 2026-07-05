"""Person data model — someone met on a trip (issue #40).

Owner-only, per-project. A person is a directory entry referenced by one or more
Encounters; it is never exposed in shared views.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Person:
    id: Optional[int] = None
    project_id: Optional[int] = None
    # All identity fields are optional — a person may be just a first name or
    # even "Unknown". Every text field is client-side searchable.
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    polarsteps: Optional[str] = None        # username or profile URL
    notes: Optional[str] = None
    avatar_photo: Optional[str] = None      # base UUID filename (no suffix), or None
