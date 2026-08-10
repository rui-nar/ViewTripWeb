"""Tests for src/tile_renderer.py's pre-render failure logging (issue #205, Unit D).

``_do_prerender`` wraps each tile's render in a bare ``except Exception: pass``
so one corrupt/failing tile never crashes the background pre-render thread
pool. That used to be completely silent; it must now also log a ``WARNING``
naming the token/tile before continuing, without changing the "never crash"
behavior.
"""
from __future__ import annotations

import logging

import src.tile_renderer as tr

_FEATURES = [
    {"geometry": {"coordinates": [[2.35, 48.85], [2.36, 48.86]]}},
]


def test_do_prerender_logs_warning_and_does_not_raise_on_render_failure(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(tr, "_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(tr, "_PRERENDER_MAX_ZOOM", 1)

    def boom(features, z, x, y):
        raise ValueError("corrupt tile data")

    monkeypatch.setattr(tr, "render_tile", boom)

    with caplog.at_level(logging.WARNING, logger="src.tile_renderer"):
        tr._do_prerender("tok123", _FEATURES)  # must not raise

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING log line for the failed pre-render"
    assert any("tok123" in r.getMessage() for r in warnings)
    # .exception()-style call: traceback must be captured, not just the message.
    assert warnings[0].exc_info is not None


def test_do_prerender_leaves_no_partial_tile_on_persistent_failure(tmp_path, monkeypatch):
    """Behavior unchanged: a persistently-failing render is a best-effort skip,
    not a crash and not a partial/corrupt file left on disk."""
    monkeypatch.setattr(tr, "_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(tr, "_PRERENDER_MAX_ZOOM", 1)
    monkeypatch.setattr(
        tr, "render_tile",
        lambda features, z, x, y: (_ for _ in ()).throw(ValueError("boom")),
    )

    tr._do_prerender("tok123", _FEATURES)  # must not raise

    token_dir = tmp_path / "tok123"
    assert not token_dir.exists() or not any(token_dir.rglob("*.png"))
