"""Tile-cache cleanup must not race the pre-render writer.

Regression: refresh_tile_cache's shutil.rmtree ran while a background
pre-render was writing tiles into the same token dir → "OSError: Directory not
empty". A per-token lock now serialises the destructive clear against the bulk
writer, and _safe_rmtree tolerates a stray concurrent write.
"""
from __future__ import annotations

import threading
import time

import src.tile_renderer as tr


def _populate(d):
    (d / "1" / "2").mkdir(parents=True)
    (d / "1" / "2" / "3.png").write_bytes(b"x")
    (d / "0" / "0").mkdir(parents=True)
    (d / "0" / "0" / "0.png").write_bytes(b"y")


def test_safe_rmtree_removes_tree_and_tolerates_missing(tmp_path):
    d = tmp_path / "tok"
    _populate(d)
    tr._safe_rmtree(d)
    assert not d.exists()
    # Second call on a now-missing dir is a no-op, not an error.
    tr._safe_rmtree(d)


def test_token_lock_is_stable_per_token_and_distinct_across_tokens():
    a1 = tr._token_lock("alpha")
    a2 = tr._token_lock("alpha")
    b = tr._token_lock("beta")
    assert a1 is a2
    assert a1 is not b


def test_rmtree_waits_for_the_token_lock(tmp_path, monkeypatch):
    """A clear must block while another worker holds the token lock — proving the
    destructive op can't run concurrently with a render."""
    monkeypatch.setattr(tr, "_CACHE_ROOT", tmp_path)
    token = "tok"
    d = tmp_path / token
    _populate(d)

    holder_released = []
    holder_has_lock = threading.Event()

    def holder():
        with tr._token_lock(token):
            holder_has_lock.set()
            time.sleep(0.2)
            holder_released.append(True)

    t = threading.Thread(target=holder)
    t.start()
    assert holder_has_lock.wait(1.0)  # holder owns the lock

    # Entering the same token lock must wait until the holder releases.
    with tr._token_lock(token):
        assert holder_released, "rmtree entered the lock before the holder released"
        tr._safe_rmtree(d)

    t.join()
    assert not d.exists()
