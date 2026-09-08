"""Delivering the published rail data onto the box (issue #345).

``scripts/fetch_rail_data.py`` is what takes a deployment from "no data" to
"``RAIL_DATA_DIR`` holds current, valid region stores plus the manifest". It
runs unattended, against files it did not build, beside workers that are
reading the directory it writes — so what is asserted here is not that it
copies bytes but that it cannot damage what is already there:

* a checksum mismatch, an HTTP failure or a manifest schema nobody knows about
  leaves the installed stores exactly as they were, and the directory still
  resolves routes;
* a re-run costs only the regions that actually changed;
* and a worker holding a store open across a refresh keeps reading valid data,
  which is the property the whole design exists for (#352, finding 2) and is
  tested by holding one open across a real refresh rather than by inspecting
  the code that performs it.

No network: the releases API, the manifest and every asset are served from
fixtures on disk, and the first-install test refuses ``socket.socket`` outright
to prove it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

import pytest

from src.rail.store import RailStore, store_filename
from src.services.rail_source import LocalRailSource, load_coverage

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "fetch_rail_data", ROOT / "scripts" / "fetch_rail_data.py"
)
fetch = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fetch
_spec.loader.exec_module(fetch)

# Two real rail-only extracts, so the store the delivery installs is a store the
# reader actually opens rather than a stand-in. They differ in size by 30x,
# which is how a test can tell which of two versions a reader is looking at.
LUXEMBOURG = ROOT / "tests" / "fixtures" / "rail" / "luxembourg-rail.osm.pbf"
MANNHEIM = ROOT / "tests" / "fixtures" / "rail_mannheim_filtered.osm.pbf"

BASE = "https://example.invalid/releases"


# ---------------------------------------------------------------------------
# A release, served from memory
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.content, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def iter_content(self, chunk_size=None):
        step = chunk_size or len(self.content) or 1
        for start in range(0, len(self.content), step):
            yield self.content[start:start + step]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _transport(bodies: dict, fail: tuple = ()):
    """A fake ``requests.get`` over {url: bytes}, and the log of what it served."""
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url in fail:
            return _Response(status=500)
        if url not in bodies:
            return _Response(status=404)
        return _Response(bodies[url])

    return get, calls


def _entry(region: str, pbf: Path, source_date: str, bbox: list) -> dict:
    body = pbf.read_bytes()
    return {
        "region": region,
        "status": "ok",
        "file": region.rsplit("/", 1)[-1] + "-rail.osm.pbf",
        "source": f"https://download.geofabrik.de/{region}-latest.osm.pbf",
        "source_date": source_date,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "bbox": bbox,
    }


# Real-ish extents: the manifest's bbox is [min_lon, min_lat, max_lon, max_lat]
# and Phase 3 selects regions by it, so the two must not overlap here or a
# per-region assertion could be answered by the other region's store.
LUX_BBOX = [5.73, 49.44, 6.53, 50.18]
DE_BBOX = [8.40, 49.40, 8.60, 49.55]


def _world(entries: list[dict], tag: str = "rail-data-2026-09-06",
           generated_at: str | None = None, schema: int = 2,
           extra_releases: list = ()) -> tuple[dict, dict]:
    """(bodies for the fake transport, the manifest that was published)."""
    if generated_at is None:
        generated_at = tag[len("rail-data-"):] + "T18:00:00Z"
    manifest = {"schema": schema, "generated_at": generated_at, "regions": entries}
    assets = [{"name": "manifest.json",
               "browser_download_url": f"{BASE}/{tag}/manifest.json"}]
    bodies = {
        fetch.RELEASES_URL.format(repo=fetch.DEFAULT_REPO): b"",
        f"{BASE}/{tag}/manifest.json":
            json.dumps(manifest).encode("utf-8"),
    }
    for entry in entries:
        if entry.get("status") != "ok":
            continue
        assets.append({"name": entry["file"],
                       "browser_download_url": f"{BASE}/{tag}/{entry['file']}"})
    releases = [
        {"tag_name": "v0.9.0", "draft": False, "assets": []},
        *extra_releases,
        {"tag_name": tag, "draft": False, "prerelease": True, "assets": assets},
    ]
    bodies[fetch.RELEASES_URL.format(repo=fetch.DEFAULT_REPO)] = json.dumps(
        releases).encode("utf-8")
    return bodies, manifest


def _with_asset(bodies: dict, entry: dict, pbf: Path,
                tag: str = "rail-data-2026-09-06") -> dict:
    bodies[f"{BASE}/{tag}/{entry['file']}"] = pbf.read_bytes()
    return bodies


def _lux(source_date="2026-09-05"):
    return _entry("europe/luxembourg", LUXEMBOURG, source_date, LUX_BBOX)


def _de(pbf=MANNHEIM, source_date="2026-09-05"):
    return _entry("europe/germany", pbf, source_date, DE_BBOX)


def _empty(region="europe/andorra"):
    return {
        "region": region,
        "status": "empty",
        "source": f"https://download.geofabrik.de/{region}-latest.osm.pbf",
        "source_date": "2026-09-05",
    }


def _ways(dest: Path, region: str) -> int:
    with RailStore(dest / store_filename(region)) as store:
        return len(store.ways_in_bbox(*store.bbox))


# ---------------------------------------------------------------------------
# First install
# ---------------------------------------------------------------------------

def test_first_install_builds_a_store_per_region(tmp_path, monkeypatch):
    """A clean directory ends up holding exactly what the manifest describes."""
    lux, de, andorra = _lux(), _de(), _empty()
    bodies, manifest = _world([lux, de, andorra])
    _with_asset(bodies, lux, LUXEMBOURG)
    _with_asset(bodies, de, MANNHEIM)
    get, calls = _transport(bodies)

    def _no_network(*a, **k):
        raise AssertionError("the delivery step opened a socket")

    monkeypatch.setattr(socket, "socket", _no_network)

    assert fetch.refresh(tmp_path, get=get) == 0

    for region in ("europe/luxembourg", "europe/germany"):
        assert (tmp_path / store_filename(region)).is_file()
    # The manifest is the release's, verbatim — including the `empty` entry,
    # which Phase 3 reads as "we know there is no rail here".
    written = json.loads((tmp_path / "manifest.json").read_text())
    assert written["schema"] == 2
    assert written["generated_at"] == manifest["generated_at"]
    assert {e["region"] for e in written["regions"]} == {
        "europe/luxembourg", "europe/germany", "europe/andorra"}
    assert [e for e in written["regions"] if e["region"] == "europe/andorra"] == [andorra]
    # Coverage is what Phase 3 will read back.
    assert sorted(r for r, _ in load_coverage(str(tmp_path))) == [
        "europe/germany", "europe/luxembourg"]
    # Nothing left behind: the extracts are deleted as soon as their store exists.
    assert list((tmp_path / fetch.WORK_DIRNAME).iterdir()) == []
    assert f"{BASE}/rail-data-2026-09-06/luxembourg-rail.osm.pbf" in calls


def test_installed_stores_answer_queries(tmp_path):
    """The delivered directory resolves, rather than merely existing."""
    lux = _lux()
    bodies, _ = _world([lux])
    _with_asset(bodies, lux, LUXEMBOURG)
    get, _ = _transport(bodies)

    fetch.refresh(tmp_path, get=get)

    source = LocalRailSource(str(tmp_path))
    assert source.regions_for((49.5, 5.8, 49.7, 6.3)) == ["europe/luxembourg"]
    assert _ways(tmp_path, "europe/luxembourg") > 0


# ---------------------------------------------------------------------------
# Re-running
# ---------------------------------------------------------------------------

def test_rerun_skips_regions_already_at_the_manifest_checksum(tmp_path):
    lux, de = _lux(), _de()
    bodies, _ = _world([lux, de])
    _with_asset(bodies, lux, LUXEMBOURG)
    _with_asset(bodies, de, MANNHEIM)

    get, _ = _transport(bodies)
    assert fetch.refresh(tmp_path, get=get) == 0
    before = (tmp_path / store_filename("europe/germany")).stat().st_mtime_ns

    get, calls = _transport(bodies)
    assert fetch.refresh(tmp_path, get=get) == 0

    assert not [c for c in calls if c.endswith(".osm.pbf")]
    assert (tmp_path / store_filename("europe/germany")).stat().st_mtime_ns == before


def test_a_changed_checksum_rebuilds_only_that_region(tmp_path):
    """A monthly rebuild that only moved one country costs only that country."""
    lux, de = _lux(), _de()
    bodies, _ = _world([lux, de])
    _with_asset(bodies, lux, LUXEMBOURG)
    _with_asset(bodies, de, MANNHEIM)
    get, _ = _transport(bodies)
    fetch.refresh(tmp_path, get=get)

    # Germany's next extract is different data under a new source date.
    de2 = _de(pbf=LUXEMBOURG, source_date="2026-10-05")
    bodies2, _ = _world([lux, de2], tag="rail-data-2026-10-06")
    _with_asset(bodies2, lux, LUXEMBOURG, tag="rail-data-2026-10-06")
    _with_asset(bodies2, de2, LUXEMBOURG, tag="rail-data-2026-10-06")
    get, calls = _transport(bodies2)

    assert fetch.refresh(tmp_path, get=get) == 0

    fetched = [c for c in calls if c.endswith(".osm.pbf")]
    assert fetched == [f"{BASE}/rail-data-2026-10-06/germany-rail.osm.pbf"]
    written = json.loads((tmp_path / "manifest.json").read_text())
    dates = {e["region"]: e["source_date"] for e in written["regions"]}
    assert dates == {"europe/luxembourg": "2026-09-05", "europe/germany": "2026-10-05"}


# ---------------------------------------------------------------------------
# Refusals — nothing good may be replaced by something broken
# ---------------------------------------------------------------------------

def test_checksum_mismatch_leaves_the_installed_store_untouched(tmp_path):
    lux = _lux()
    bodies, _ = _world([lux])
    _with_asset(bodies, lux, LUXEMBOURG)
    get, _ = _transport(bodies)
    fetch.refresh(tmp_path, get=get)
    good = (tmp_path / store_filename("europe/luxembourg")).read_bytes()
    ways = _ways(tmp_path, "europe/luxembourg")

    # A newer release whose asset does not match the checksum it publishes —
    # a truncated upload, a corrupted mirror, a swapped file.
    corrupt = _lux(source_date="2026-10-05")
    corrupt["sha256"] = "0" * 64
    bodies2, _ = _world([corrupt], tag="rail-data-2026-10-06")
    _with_asset(bodies2, corrupt, MANNHEIM, tag="rail-data-2026-10-06")
    get, _ = _transport(bodies2)

    assert fetch.refresh(tmp_path, get=get) == 1

    assert (tmp_path / store_filename("europe/luxembourg")).read_bytes() == good
    assert _ways(tmp_path, "europe/luxembourg") == ways
    # The manifest still describes what is on disk, not what was refused.
    written = json.loads((tmp_path / "manifest.json").read_text())
    assert [e["source_date"] for e in written["regions"]] == ["2026-09-05"]
    assert written["generated_at"] == "2026-09-06T18:00:00Z"
    assert list((tmp_path / fetch.WORK_DIRNAME).iterdir()) == []


def test_partial_failure_keeps_the_other_regions_usable(tmp_path):
    """One region failing must not cost the rest their data — or their coverage."""
    lux, de = _lux(), _de()
    bodies, _ = _world([lux, de])
    _with_asset(bodies, lux, LUXEMBOURG)
    _with_asset(bodies, de, MANNHEIM)
    get, _ = _transport(bodies)
    fetch.refresh(tmp_path, get=get)
    de_ways = _ways(tmp_path, "europe/germany")

    # Both regions move on; Germany's asset is unreachable this time.
    lux2, de2 = _lux("2026-10-05"), _de(pbf=LUXEMBOURG, source_date="2026-10-05")
    bodies2, _ = _world([lux2, de2], tag="rail-data-2026-10-06")
    _with_asset(bodies2, lux2, LUXEMBOURG, tag="rail-data-2026-10-06")
    _with_asset(bodies2, de2, LUXEMBOURG, tag="rail-data-2026-10-06")
    get, _ = _transport(
        bodies2, fail=(f"{BASE}/rail-data-2026-10-06/germany-rail.osm.pbf",))

    assert fetch.refresh(tmp_path, get=get) == 1

    # Germany keeps the store and the manifest entry it had, so it still routes.
    assert _ways(tmp_path, "europe/germany") == de_ways
    written = json.loads((tmp_path / "manifest.json").read_text())
    entries = {e["region"]: e for e in written["regions"]}
    assert entries["europe/germany"]["source_date"] == "2026-09-05"
    assert entries["europe/luxembourg"]["source_date"] == "2026-10-05"
    # A partial run does not claim the release's freshness.
    assert written["generated_at"] == "2026-09-06T18:00:00Z"
    assert sorted(r for r, _ in load_coverage(str(tmp_path))) == [
        "europe/germany", "europe/luxembourg"]

    # And the re-run converges: only the region that failed is fetched again.
    get, calls = _transport(bodies2)
    assert fetch.refresh(tmp_path, get=get) == 0
    assert [c for c in calls if c.endswith(".osm.pbf")] == [
        f"{BASE}/rail-data-2026-10-06/germany-rail.osm.pbf"]
    written = json.loads((tmp_path / "manifest.json").read_text())
    assert {e["source_date"] for e in written["regions"]} == {"2026-10-05"}
    # Complete now, so the directory may claim the release's generation date.
    assert written["generated_at"] == "2026-10-06T18:00:00Z"


def test_an_unknown_manifest_schema_is_refused(tmp_path):
    lux = _lux()
    bodies, _ = _world([lux])
    _with_asset(bodies, lux, LUXEMBOURG)
    get, _ = _transport(bodies)
    fetch.refresh(tmp_path, get=get)
    before = sorted(p.name for p in tmp_path.iterdir())

    future = _lux("2026-10-05")
    bodies2, _ = _world([future], tag="rail-data-2026-10-06", schema=3)
    _with_asset(bodies2, future, MANNHEIM, tag="rail-data-2026-10-06")
    get, calls = _transport(bodies2)

    with pytest.raises(fetch.RailDataError, match="schema"):
        fetch.refresh(tmp_path, get=get)

    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not [c for c in calls if c.endswith(".osm.pbf")]
    assert json.loads((tmp_path / "manifest.json").read_text())["schema"] == 2


def test_no_rail_release_is_an_error_not_an_empty_install(tmp_path):
    bodies = {fetch.RELEASES_URL.format(repo=fetch.DEFAULT_REPO):
              json.dumps([{"tag_name": "v0.9.0", "draft": False, "assets": []}]).encode()}
    get, _ = _transport(bodies)

    with pytest.raises(fetch.RailDataError, match="rail-data"):
        fetch.refresh(tmp_path, get=get)

    assert not (tmp_path / "manifest.json").exists()


def test_an_empty_region_fetches_nothing(tmp_path):
    andorra = _empty()
    bodies, _ = _world([andorra])
    get, calls = _transport(bodies)

    assert fetch.refresh(tmp_path, get=get) == 0

    assert not (tmp_path / store_filename("europe/andorra")).exists()
    assert not [c for c in calls if c.endswith(".osm.pbf")]
    assert load_coverage(str(tmp_path)) == []
    assert json.loads((tmp_path / "manifest.json").read_text())["regions"] == [andorra]


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def test_an_explicit_tag_installs_that_release(tmp_path):
    """The rollback path: pin the previous release and get its data back."""
    # Last month's extract for the same region, holding different data.
    old = _entry("europe/luxembourg", MANNHEIM, "2026-08-05", LUX_BBOX)
    old_bodies, _ = _world([old], tag="rail-data-2026-08-06")
    _with_asset(old_bodies, old, MANNHEIM, tag="rail-data-2026-08-06")
    old_release = json.loads(
        old_bodies[fetch.RELEASES_URL.format(repo=fetch.DEFAULT_REPO)])[-1]

    new = _lux("2026-09-05")
    bodies, _ = _world([new], extra_releases=[old_release])
    _with_asset(bodies, new, LUXEMBOURG)
    bodies.update({k: v for k, v in old_bodies.items() if k.startswith(BASE)})
    get, _ = _transport(bodies)

    assert fetch.refresh(tmp_path, get=get) == 0
    assert _ways(tmp_path, "europe/luxembourg") == _lux_ways()

    get, _ = _transport(bodies)
    assert fetch.refresh(tmp_path, get=get, tag="rail-data-2026-08-06") == 0

    written = json.loads((tmp_path / "manifest.json").read_text())
    assert written["regions"][0]["source_date"] == "2026-08-05"
    assert _ways(tmp_path, "europe/luxembourg") != _lux_ways()


def _lux_ways(_cache={}):
    """Way count of the Luxembourg fixture, built once."""
    if "n" not in _cache:
        import tempfile

        from src.rail.builder import build_store

        out = Path(tempfile.mkdtemp()) / "lux.sqlite"
        build_store(LUXEMBOURG, out)
        with RailStore(out) as store:
            _cache["n"] = len(store.ways_in_bbox(*store.bbox))
    return _cache["n"]


# ---------------------------------------------------------------------------
# The image this runs in
# ---------------------------------------------------------------------------

def test_the_image_can_import_osmium():
    """The delivery step builds stores in the app image, so it needs libexpat.

    ``python:*-slim`` provides no libexpat.so.1 — CPython statically links its
    own copy for ``pyexpat`` — so pyosmium's extension module fails to import
    there however it was installed. Verified against the base image: with the
    whole of requirements.txt installed and no libexpat1, ``import osmium``
    raises ``ImportError: libexpat.so.1``.

    Nothing else in the image imports osmium, which is exactly why this is
    asserted: the apt layer looks like dead weight and deleting it breaks the
    rail refresh on the box, not in CI.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "libexpat1" in dockerfile


# ---------------------------------------------------------------------------
# The property the design exists for
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has no share-delete rename: os.replace over a file SQLite "
           "holds open raises PermissionError, so the property cannot exist "
           "there. Production is Linux containers; this asserts the POSIX "
           "guarantee the design depends on.",
)
def test_a_reader_holding_a_store_open_survives_a_refresh(tmp_path):
    """The atomic-rename contract, exercised rather than asserted about.

    ``LocalRailSource`` guards *opening* a store, not querying one, so a worker
    that already holds a connection when the file underneath it changes raises
    ``sqlite3.DatabaseError`` out of the RQ job (#345 Phase 3's known gap, #352
    finding 2). Renaming a fully built store into place keeps the old inode
    alive for that connection, so the query in flight finishes against the data
    it started on and only the *next* open sees the new data.

    Replace the ``os.replace`` in ``install_region`` with anything that writes
    the destination in place and this test fails: the held-open reader either
    starts seeing the new region's rows or raises on a file that changed under
    it.
    """
    de = _de(pbf=MANNHEIM)
    bodies, _ = _world([de])
    _with_asset(bodies, de, MANNHEIM)
    get, _ = _transport(bodies)
    fetch.refresh(tmp_path, get=get)

    path = tmp_path / store_filename("europe/germany")
    reader = RailStore(path)
    before = reader.ways_in_bbox(*reader.bbox)
    assert before

    # The next month's build for the same region is entirely different data.
    de2 = _de(pbf=LUXEMBOURG, source_date="2026-10-05")
    bodies2, _ = _world([de2], tag="rail-data-2026-10-06")
    _with_asset(bodies2, de2, LUXEMBOURG, tag="rail-data-2026-10-06")
    get, _ = _transport(bodies2)
    assert fetch.refresh(tmp_path, get=get) == 0

    # The open connection still reads the data it was opened on, in full.
    after = reader.ways_in_bbox(*reader.bbox)
    assert after == before
    reader.close()

    # And a reader opening it now gets the new data — the refresh did happen.
    with RailStore(path) as fresh:
        assert len(fresh.ways_in_bbox(*fresh.bbox)) != len(before)
