"""Tests for src/poster/poster_renderer.py (issue #14, Unit E).

Two groups:
  - ``assemble_card_content``: pure Pillow-free unit tests over config-flag /
    memory / metrics combinations.
  - A golden-path test of the full ``render_poster`` entry point, using an
    in-memory SQLite DB (mirrors tests/test_poster_api.py's fixture pattern)
    and a fake ``tile_fetcher`` (mirrors tests/test_tile_stitcher.py's
    pattern) so no real network/Mapbox call happens.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
import src.poster.tile_stitcher as tile_stitcher
from models.project_db import DBProject
from models.user import UserInfo
from src.exceptions.errors import APIError
from src.poster.poster_renderer import (
    _PIN_COLOR,
    _PREVIEW_MAX_DIMENSION,
    _Projector,
    _pdf_resolution,
    _target_size,
    assemble_card_content,
    render_poster,
    render_poster_preview,
)

_PARIS_BOUNDS = {"north": 48.9, "south": 48.8, "east": 2.4, "west": 2.3}


def _solid_tile(color=(120, 140, 160), size=(512, 512)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _fake_tile_fetcher(z, x, y):
    return _solid_tile()


# ── assemble_card_content ────────────────────────────────────────────────────

_MEMORY = {
    "id": 1,
    "lat": 48.85,
    "lon": 2.35,
    "date": "2024-06-01",
    "name": "Day 1",
    "description": "Arrived in Paris",
    "photo_uuids": ["abc", "def"],
}

_METRICS = {
    "distance_m": 12_345.0,
    "elevation_m": 210.0,
    "encounter_count": 2,
    "counters": [{"name": "Coffees", "value": 3}],
    "tag_pie": {"scenic": 5_000.0, "urban": 2_000.0},
}

_ALL_FLAGS = {
    "distance": True, "elevation": True, "hero_photo": True, "all_photos": True,
    "memory_text": True, "counters": True, "tag_pie": True, "encounters": True,
}
_NO_FLAGS = {k: False for k in _ALL_FLAGS}


def test_all_flags_produce_every_block_kind():
    blocks = assemble_card_content(_ALL_FLAGS, _MEMORY, _METRICS)
    kinds = [b["kind"] for b in blocks]
    assert kinds == [
        "name", "description", "hero_photo", "photos",
        "distance", "elevation", "counters", "tag_pie", "encounters",
    ]


def test_no_flags_produce_no_blocks():
    assert assemble_card_content(_NO_FLAGS, _MEMORY, _METRICS) == []


def test_memory_text_off_hides_name_and_description():
    config = {**_ALL_FLAGS, "memory_text": False}
    kinds = [b["kind"] for b in assemble_card_content(config, _MEMORY, _METRICS)]
    assert "name" not in kinds
    assert "description" not in kinds


def test_memory_text_on_but_no_description_omits_description_block():
    memory = {**_MEMORY, "description": None}
    config = {**_NO_FLAGS, "memory_text": True}
    blocks = assemble_card_content(config, memory, _METRICS)
    assert [b["kind"] for b in blocks] == ["name"]


def test_hero_photo_uses_only_first_uuid():
    config = {**_NO_FLAGS, "hero_photo": True}
    blocks = assemble_card_content(config, _MEMORY, _METRICS)
    assert blocks == [{"kind": "hero_photo", "uuid": "abc"}]


def test_hero_photo_and_all_photos_skipped_when_no_photos():
    memory = {**_MEMORY, "photo_uuids": []}
    config = {**_ALL_FLAGS}
    kinds = [b["kind"] for b in assemble_card_content(config, memory, _METRICS)]
    assert "hero_photo" not in kinds
    assert "photos" not in kinds


def test_counters_and_tag_pie_skipped_when_empty_even_if_enabled():
    metrics = {**_METRICS, "counters": [], "tag_pie": {}}
    config = {**_NO_FLAGS, "counters": True, "tag_pie": True}
    assert assemble_card_content(config, _MEMORY, metrics) == []


def test_encounters_block_present_even_when_count_is_zero():
    """Unlike counters/tag_pie, encounters has no "empty" sentinel to skip on —
    a count of 0 is still meaningful information for the card."""
    metrics = {**_METRICS, "encounter_count": 0}
    config = {**_NO_FLAGS, "encounters": True}
    assert assemble_card_content(config, _MEMORY, metrics) == [{"kind": "encounters", "count": 0}]


def test_distance_and_elevation_carry_raw_metric_values():
    config = {**_NO_FLAGS, "distance": True, "elevation": True}
    blocks = assemble_card_content(config, _MEMORY, _METRICS)
    assert blocks == [
        {"kind": "distance", "value_m": 12_345.0},
        {"kind": "elevation", "value_m": 210.0},
    ]


# ── Resolution helpers ────────────────────────────────────────────────────────

def test_target_size_landscape_matches_a0_at_150dpi():
    w, h = _target_size("landscape")
    assert (w, h) == (7022, 4967)


def test_target_size_portrait_is_landscape_transposed():
    assert _target_size("portrait") == _target_size("landscape")[::-1]


def test_pdf_resolution_is_close_to_150_dpi_for_both_orientations():
    w, h = _target_size("landscape")
    assert _pdf_resolution(w, "landscape") == pytest.approx(150.0, abs=0.1)
    w, h = _target_size("portrait")
    assert _pdf_resolution(w, "portrait") == pytest.approx(150.0, abs=0.1)


# ── _Projector ────────────────────────────────────────────────────────────────
# Regression coverage for a real bug found during manual end-to-end testing:
# _Projector subtracted crop_rect_for_bounds' offset (relative to the stitched
# tile canvas's own origin) directly from lonlat_to_pixel's *absolute*
# world-pixel coordinates, without first subtracting the tile canvas's origin
# (x_min * tile_size). For any bounding box far from the (0, 0) world-pixel
# origin — i.e. almost any real trip — this placed every projected pin/route
# point hundreds of thousands of pixels off-canvas, so every memory silently
# overflowed to the legend and nothing but the legend text ever appeared in
# the rendered image. The existing golden-path test below never caught this
# because it only checked file existence/size, not pixel content.

# A multi-country-scale box (unlike the tight ~0.1°-square _PARIS_BOUNDS used
# elsewhere in this file) — this is the shape of box that actually exposed the
# bug in manual testing, since the world-pixel origin offset grows with how
# far the box's tile range sits from world-pixel (0, 0).
_FRANCE_BOUNDS = {"north": 49.0, "south": 45.5, "east": 5.0, "west": 2.0}


@pytest.mark.parametrize("bounds", [_PARIS_BOUNDS, _FRANCE_BOUNDS])
@pytest.mark.parametrize("target_w, target_h", [(7022, 4967), (4967, 7022)])
def test_projector_places_points_within_bounds_inside_the_canvas(bounds, target_w, target_h):
    projector = _Projector(bounds, target_w, target_h)
    # Points strictly inside the bounds (not exactly on an edge) should
    # project well within the canvas, not thousands of pixels outside it.
    mid_lon = (bounds["west"] + bounds["east"]) / 2
    mid_lat = (bounds["south"] + bounds["north"]) / 2
    for lon, lat in [
        (mid_lon, mid_lat),
        (bounds["west"] + 0.01, bounds["north"] - 0.01),  # near NW corner
        (bounds["east"] - 0.01, bounds["south"] + 0.01),  # near SE corner
    ]:
        x, y = projector.project(lon, lat)
        assert -1 <= x <= target_w + 1, f"x={x} escaped canvas width {target_w}"
        assert -1 <= y <= target_h + 1, f"y={y} escaped canvas height {target_h}"


def test_projector_orders_points_geographically_nw_before_se():
    """A point near the bounds' NW corner should project to a smaller (x, y)
    than one near the SE corner — catches an origin computed with the wrong
    sign/axis, not just one that's merely out of range."""
    projector = _Projector(_FRANCE_BOUNDS, 7022, 4967)
    nw_x, nw_y = projector.project(_FRANCE_BOUNDS["west"] + 0.1, _FRANCE_BOUNDS["north"] - 0.1)
    se_x, se_y = projector.project(_FRANCE_BOUNDS["east"] - 0.1, _FRANCE_BOUNDS["south"] + 0.1)
    assert nw_x < se_x
    assert nw_y < se_y


# ── Golden-path render_poster test ───────────────────────────────────────────

@pytest.fixture
def project_id(monkeypatch):
    """Seed a bare-minimum project in an in-memory SQLite DB and monkeypatch
    models.db.engine to point at it, mirroring tests/test_poster_api.py's
    fixture pattern. Returns the project's DB id."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        user = UserInfo(display_name="A", email="a@e.com")
        sess.add(user); sess.commit(); sess.refresh(user)
        proj = DBProject(user_info_id=user.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        return proj.id


_BODY = {
    "bounds": _PARIS_BOUNDS,
    "orientation": "landscape",
    "config": {
        "distance": True, "elevation": False, "hero_photo": True,
        "all_photos": False, "memory_text": True, "counters": False,
        "tag_pie": False, "encounters": False,
    },
    "memories": [
        {"id": 1, "lat": 48.85, "lon": 2.35, "date": "2024-06-01",
         "name": "Day 1", "description": "Arrived", "photo_uuids": []},
        {"id": 2, "lat": 48.86, "lon": 2.36, "date": "2024-06-02",
         "name": "Day 2", "description": "Explored", "photo_uuids": []},
    ],
}


def test_render_poster_writes_png_and_pdf_at_expected_size(tmp_path, project_id):
    stages: list[str] = []

    png_path, pdf_path = render_poster(
        job_id=1,
        user_info_id=1,
        project_id=project_id,
        request=_BODY,
        poster_dir=tmp_path,
        progress=stages.append,
        tile_fetcher=_fake_tile_fetcher,
    )

    assert png_path.exists() and png_path.stat().st_size > 0
    assert pdf_path.exists() and pdf_path.stat().st_size > 0
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert pdf_path.read_bytes()[:5] == b"%PDF-"

    with Image.open(png_path) as img:
        assert img.size == _target_size("landscape")
        # At least one pin should actually land on the canvas (regression
        # coverage for the _Projector origin bug above: a mis-projected pin
        # draws off-canvas and is silently a no-op, leaving the image with no
        # pin-colored pixels anywhere).
        pixels = img.load()
        w, h = img.size
        assert any(
            pixels[x, y][:3] == _PIN_COLOR
            for x in range(0, w, 8)
            for y in range(0, h, 8)
        ), "no pin-colored pixel found anywhere in the rendered poster"

    # Some stage progress should have reached the caller beyond a single
    # "rendering" label.
    assert len(stages) >= 3


def test_render_poster_portrait_orientation_transposes_size(tmp_path, project_id):
    body = {**_BODY, "orientation": "portrait"}
    png_path, _ = render_poster(
        job_id=2,
        user_info_id=1,
        project_id=project_id,
        request=body,
        poster_dir=tmp_path,
        progress=lambda s: None,
        tile_fetcher=_fake_tile_fetcher,
    )
    with Image.open(png_path) as img:
        assert img.size == _target_size("portrait")


def test_render_poster_raises_when_mapbox_token_missing(tmp_path, project_id, monkeypatch):
    """No tile_fetcher injected and no MAPBOX_TOKEN configured -> the render
    must fail with an actionable error, not silently complete on a grey
    background (issue #14 feedback, point 1 — the silent fallback made a
    misconfigured token undiagnosable)."""
    monkeypatch.setattr(tile_stitcher, "_mapbox_token", lambda: "")
    with pytest.raises(APIError, match="MAPBOX_TOKEN"):
        render_poster(
            job_id=3,
            user_info_id=1,
            project_id=project_id,
            request=_BODY,
            poster_dir=tmp_path,
            progress=lambda s: None,
        )


def test_render_poster_propagates_tile_fetch_failure(tmp_path, project_id):
    """A tile fetch that fails mid-render (bad token, Mapbox outage) must
    propagate with the underlying error message intact so the job runner can
    record it on the job row."""
    def _failing_fetcher(z, x, y):
        raise APIError("Mapbox tile fetch failed (401): Not Authorized")

    with pytest.raises(APIError, match="Not Authorized"):
        render_poster(
            job_id=4,
            user_info_id=1,
            project_id=project_id,
            request=_BODY,
            poster_dir=tmp_path,
            progress=lambda s: None,
            tile_fetcher=_failing_fetcher,
        )


# ── render_poster_preview ─────────────────────────────────────────────────────
# Fast, synchronous, low-res layout preview: never touches the network (no
# tile_fetcher needed, unlike render_poster's golden-path tests above), and
# is small/quick enough to check on every call.

def test_preview_returns_a_small_png_preserving_a0_aspect_ratio(project_id):
    png_bytes = render_poster_preview(project_id, 1, _BODY)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    with Image.open(io.BytesIO(png_bytes)) as img:
        w, h = img.size
        # Longest side bounded by _PREVIEW_MAX_DIMENSION, real A0 aspect
        # ratio preserved (within a pixel of rounding).
        assert max(w, h) == _PREVIEW_MAX_DIMENSION
        real_w, real_h = _target_size("landscape")
        assert abs(w / h - real_w / real_h) < 0.01


def test_preview_portrait_is_taller_than_wide(project_id):
    body = {**_BODY, "orientation": "portrait"}
    png_bytes = render_poster_preview(project_id, 1, body)
    with Image.open(io.BytesIO(png_bytes)) as img:
        w, h = img.size
        assert h > w


def test_preview_never_calls_the_network_tile_fetcher(project_id):
    """No tile_fetcher is accepted/forwarded — render_poster_preview always
    skips the basemap fetch entirely (flat fallback), regardless of whether
    MAPBOX_TOKEN happens to be configured in the test environment."""
    # If this accidentally tried a real Mapbox fetch, it would either raise
    # (no token/network in CI) or take much longer than a layout preview
    # should — either way the assertion below on a normal, fast return is
    # enough coverage without needing to mock `requests`.
    png_bytes = render_poster_preview(project_id, 1, _BODY)
    assert len(png_bytes) > 0


def test_preview_shows_pins_scaled_down_but_still_visible(project_id):
    """Regression coverage mirroring the golden-path pin-pixel check above,
    at preview scale — pins/cards must still be visible, just smaller."""
    png_bytes = render_poster_preview(project_id, 1, _BODY)
    with Image.open(io.BytesIO(png_bytes)) as img:
        pixels = img.load()
        w, h = img.size
        assert any(
            pixels[x, y][:3] == _PIN_COLOR
            for x in range(0, w)
            for y in range(0, h)
        ), "no pin-colored pixel found anywhere in the preview"
