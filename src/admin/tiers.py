"""Per-user encryption tier for the admin dashboard.

The E2EE tables do NOT exist on this branch, so ``user_encryption_tier`` is a
stub returning ``"none"`` for everyone. A future E2EE merge will read the user's
E2EE row and feed it through the pure :func:`tier_from` mapping.

Tiers, ordered by strength:
  * none   — no encryption
  * low    — server-held escrow (recoverable by the operator)
  * medium — Q&A / security-question recovery
  * high   — recovery key / passphrase (zero-knowledge; unrecoverable server-side)
"""
from __future__ import annotations

_METHOD_TO_TIER = {
    "escrow": "low",
    "qna": "medium",
    "recovery_key": "high",
    "passphrase": "high",
}


def tier_from(enabled: bool, method: str | None) -> str:
    """Pure mapping from (enabled, method) to an encryption tier string.

    Disabled encryption is always ``"none"`` regardless of method. An unknown or
    missing method on an enabled account falls back to ``"none"`` (fail safe: an
    unrecognised scheme is not assumed recoverable).
    """
    if not enabled:
        return "none"
    return _METHOD_TO_TIER.get(method or "", "none")


def user_encryption_tier(sess, user_info_id: int) -> str:
    """Encryption tier for a user. Stub → ``"none"`` (E2EE tables absent here).

    Signature takes ``(sess, user_info_id)`` so a future E2EE merge can read the
    user's row and delegate to :func:`tier_from` without changing callers.
    """
    return "none"
