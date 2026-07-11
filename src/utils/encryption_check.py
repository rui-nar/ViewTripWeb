"""Shared server-side check for client-side E2EE ciphertext envelopes (issue #26).

The server never holds the key material and never decrypts field content — it
only needs a cheap structural test to tell ciphertext apart from plaintext so
it can (a) skip fields it can't safely read/derive from (GPS decode, JSON
parse, third-party translation) and (b) avoid clobbering an already-encrypted
row on a background write (Strava/Polarsteps sync, activity enrichment).

Originally lived as a private helper in api/memories.py (issue #26/#27);
promoted here so api/memories.py and api/share.py (issue #28) share one
implementation.
"""
from __future__ import annotations

from typing import Optional


def is_encrypted_envelope(value: Optional[str]) -> bool:
    """True if *value* looks like a client-side E2EE ciphertext envelope
    (`v1.<b64 wrapped DEK>.<b64 ciphertext>`, see `EncryptedField` in
    flutter_client/lib/src/crypto/e2ee_crypto.dart) rather than plaintext.

    Cheap structural check only — the server cannot and does not decrypt.
    """
    if not value:
        return False
    parts = value.split(".")
    return len(parts) == 3 and parts[0] == "v1"
