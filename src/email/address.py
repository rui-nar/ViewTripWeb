"""Email address validation and normalisation (issue #110).

One shared implementation, because pending invites are matched by comparing a
stored address to a registered one: if the invite path and the registration
path normalised differently — one lowercasing, the other not — an invite sent
to ``Alice@Example.com`` would silently never match the account registered as
``alice@example.com``. The bug would look like "invites don't arrive" and be
invisible in both modules separately.

The regex is a deliberate sanity check, not RFC 5322 validation (which is
famously not expressible as a readable regex, and which still would not tell
you whether the mailbox exists). Anything that gets past it and is genuinely
undeliverable fails at send time and is logged there; what this catches is
obviously-not-an-address input, before an account is created around it.
"""
from __future__ import annotations

import re

# Local part: anything without whitespace or "@". Domain: same, plus at least
# one dot so bare hostnames ("alice@localhost") are rejected — a sending
# domain is required for any of this mail to leave the building.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    """True if *value* is plausibly an email address."""
    return bool(_EMAIL_RE.match(value.strip()))


def normalize_email(value: str) -> str:
    """Canonical form used for storage and for all invite matching.

    Lowercased and stripped. The local part is case-sensitive per spec, but no
    provider in practice treats it that way, and matching case-sensitively here
    would strand invites sent to a differently-cased spelling of a real address.
    """
    return value.strip().lower()
