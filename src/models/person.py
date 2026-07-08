"""Person data model — someone met on a trip (issue #40).

Owner-only, per-project. A person is a directory entry referenced by one or more
Encounters; it is never exposed in shared views.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


def polarsteps_from_socials(socials: Optional[List[Dict[str, str]]]) -> Optional[str]:
    """Return the handle of the first "polarsteps" social entry, or None.

    Used to mirror the multi-network socials list back onto the dedicated
    `polarsteps` column so the "view a person's shared Polarsteps trip" feature
    (which reads that column) keeps working (issue #49).
    """
    for entry in socials or []:
        if (entry.get("network") or "").strip().lower() == "polarsteps":
            handle = (entry.get("handle") or "").strip()
            return handle or None
    return None


@dataclass
class Person:
    id: Optional[int] = None
    project_id: Optional[int] = None
    # All identity fields are optional — a person may be just a first name or
    # even "Unknown". Every text field is client-side searchable.
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    polarsteps: Optional[str] = None        # username or profile URL (mirror of the socials polarsteps entry)
    notes: Optional[str] = None
    avatar_photo: Optional[str] = None      # base UUID filename (no suffix), or None
    socials: List[Dict[str, str]] = field(default_factory=list)  # [{"network", "handle"}, …]
    nationalities: List[str] = field(default_factory=list)       # ISO 3166-1 alpha-2 codes
    residence: Optional[str] = None         # "city, country" where they live
