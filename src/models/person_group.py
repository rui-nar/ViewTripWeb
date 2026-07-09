"""Person-group data model — a named group of people met on a trip (issue #50).

Owner-only, per-project. A group has 0+ member people (each Person carries a
nullable ``group_id``), plus its own name, nationalities and social links. Never
exposed in shared views.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PersonGroup:
    id: Optional[int] = None
    project_id: Optional[int] = None
    name: Optional[str] = None                                    # optional label
    nationalities: List[str] = field(default_factory=list)       # ISO 3166-1 alpha-2 codes
    socials: List[Dict[str, str]] = field(default_factory=list)  # [{"network", "handle"}, …]
