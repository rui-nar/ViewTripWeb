"""Per-entity lock for serializing photos_json read-modify-write (issue #237).

Memories and journal entries both store their photo list as a single JSON
array on the row (``photos_json``). Concurrent background photo downloads
(queued via ``/photos/from-url``) each do their own read -> mutate -> write
of that column with no row-level locking, so two downloads finishing close
together can race: whichever commits last silently clobbers the other's
update, scrambling order or dropping a photo. Callers wrap that
read-modify-write critical section in the lock returned here, keyed by
(entity_kind, entity_id) so memories and journal entries never contend with
each other.

Mirrors the dict-of-locks idiom already used for coalesced background
refreshes in ``api/project_shared.py`` (``_coalesce_lock``/``_coalesce_state``).
"""
from __future__ import annotations

import threading
from typing import Dict, Tuple

_registry_lock = threading.Lock()
_locks: Dict[Tuple[str, int], threading.Lock] = {}


def photo_lock(entity_kind: str, entity_id: int) -> threading.Lock:
    """Return the lock guarding *entity_id*'s ``photos_json`` (created on first use)."""
    key = (entity_kind, entity_id)
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock
