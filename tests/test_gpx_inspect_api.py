"""The dry run, and an import that trusts the file (#260, unit 4).

The first version of this import asked for a date, a start time, an end time and
an activity type up front, and only then told you whether the file was
acceptable at all. `inspect` inverts that: it reads the file, writes nothing,
and hands back everything needed to show a preview with every field already
filled in — so the user confirms rather than transcribes.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.activities import router as activities_router
from api.deps import get_current_user
from models.project_db import DBActivity, DBProject, DBProjectItem, DBProjectMember
from models.user import UserInfo

_HEADER = ('<?xml version="1.0"?>'
           '<gpx version="1.1" creator="test" '
           'xmlns="http://www.topografix.com/GPX/1/1">')
_START = datetime(2024, 8, 12, 7, 33, 0, tzinfo=timezone.utc)


def _timed_track(count=40, name="Morning ride", activity_type="cycling",
                 step_m=14.0, seconds=1):
    """A recorded track that knows its own name, type and clock."""
    parts = [_HEADER, "<trk>", f"<name>{name}</name>",
             f"<type>{activity_type}</type>", "<trkseg>"]
    when = _START
    for i in range(count):
        lat = 46.0 + i * (step_m / 111320.0)
        parts.append(f'<trkpt lat="{lat}" lon="6.0"><ele>{500 + i}</ele>'
                     f'<time>{when.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>')
        when += timedelta(seconds=seconds)
    parts += ["</trkseg>", "</trk>", "</gpx>"]
    return "".join(parts).encode("utf-8")


def _route(count=6, name="Planned loop"):
    """A planner's export: no clock, no elevation, just a line."""
    parts = [_HEADER, "<rte>", f"<name>{name}</name>"]
    for i in range(count):
        parts.append(f'<rtept lat="{45.0 + i * 0.01}" lon="6.0"/>')
    parts += ["</rte>", "</gpx>"]
    return "".join(parts).encode("utf-8")


def _two_tracks():
    first = _timed_track(count=10, name="Lap 1").decode()
    second = ("<trk><name>Lap 2</name><trkseg>"
              '<trkpt lat="45.0" lon="5.0"/><trkpt lat="45.1" lon="5.1"/>'
              '<trkpt lat="45.2" lon="5.2"/></trkseg></trk></gpx>')
    return first.replace("</gpx>", second).encode("utf-8")


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        viewer = UserInfo(display_name="Viewer", email="viewer@e.com")
        sess.add(owner); sess.add(viewer); sess.commit()
        sess.refresh(owner); sess.refresh(viewer)
        project = DBProject(user_info_id=owner.id, name="Trip")
        sess.add(project); sess.commit(); sess.refresh(project)
        sess.add(DBProjectMember(
            project_id=project.id, user_info_id=viewer.id, role="viewer",
            invited_by=owner.id, created_at=time.time()))
        sess.commit()
        ids = {"owner": owner.id, "viewer": viewer.id}

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(activities_router)

    def act_as(who):
        current["uid"] = ids[who]

    return TestClient(app), engine, ids, act_as


def _inspect(client, content=None, filename="track.gpx", owner=None):
    return client.post(
        "/api/projects/Trip/activities/gpx/inspect",
        params={"owner": owner} if owner is not None else {},
        files={"file": (filename, content or _timed_track(),
                        "application/gpx+xml")})


def _import(client, content=None, filename="track.gpx", **fields):
    return client.post(
        "/api/projects/Trip/activities/import-gpx",
        files={"file": (filename, content or _timed_track(),
                        "application/gpx+xml")},
        data={k: v for k, v in fields.items() if v is not None})


def _activity_count(engine):
    with Session(engine) as sess:
        return len(sess.exec(select(DBActivity)).all())


class TestInspectWritesNothing:
    def test_inspecting_leaves_the_database_alone(self, env):
        """The whole point of a dry run. If this ever writes, the preview
        becomes a commitment and the user's 'Cancel' stops meaning anything."""
        client, engine, *_ = env
        before = _activity_count(engine)

        assert _inspect(client).status_code == 200

        assert _activity_count(engine) == before

    def test_a_viewer_may_not_inspect(self, env):
        """Reading a file into a trip you cannot add to has no purpose."""
        client, _engine, ids, act_as = env
        act_as("viewer")
        # The owner param is how another user's trip is addressed at all;
        # without it the name resolves against the viewer's own trips and the
        # answer is a 404 rather than a refusal.
        assert _inspect(client, owner=ids["owner"]).status_code == 403


class TestInspectReadsTheFile:
    def test_it_reports_what_the_track_says(self, env):
        client, *_ = env
        body = _inspect(client).json()

        assert len(body["candidates"]) == 1
        only = body["candidates"][0]
        assert only["name"] == "Morning ride"
        assert only["activity_type"] == "ride"        # mapped from "cycling"
        assert only["point_count"] == 40
        assert only["is_route"] is False
        assert only["has_times"] is True
        assert only["started_at"].startswith("2024-08-12T07:33")
        assert only["elapsed_seconds"] == 39
        assert only["errors"] == []

    def test_the_climb_is_reported_as_an_estimate(self, env):
        """Elevation U2. The app measures this itself rather than being told it,
        so every surface that shows it has to say so."""
        client, *_ = env
        only = _inspect(client).json()["candidates"][0]
        assert only["elevation_gain_m"] is not None
        assert only["elevation_gain_estimated"] is True

    def test_a_route_reports_no_clock(self, env):
        client, *_ = env
        body = _inspect(client, content=_route()).json()

        only = body["candidates"][0]
        assert only["is_route"] is True
        assert only["has_times"] is False
        assert only["started_at"] is None
        assert only["moving_seconds"] is None
        assert only["errors"] == []

    def test_every_track_is_offered_with_its_own_verdict(self, env):
        client, *_ = env
        body = _inspect(client, content=_two_tracks()).json()

        assert [c["name"] for c in body["candidates"]] == ["Lap 1", "Lap 2"]
        assert all(c["errors"] == [] for c in body["candidates"])
        assert body["candidates"][1]["index"] == 1

    def test_a_file_with_nothing_in_it_says_why(self, env):
        client, *_ = env
        body = _inspect(client, content=(
            _HEADER + '<wpt lat="46.0" lon="6.0"/></gpx>').encode()).json()

        assert body["candidates"] == []
        assert any("only waypoints" in e.lower() for e in body["errors"])

    def test_a_track_already_in_the_trip_is_flagged(self, env):
        """So the dialog can offer to open it rather than only refusing later."""
        client, *_ = env
        first = _import(client)
        assert first.status_code == 200, first.text

        body = _inspect(client).json()

        assert body["duplicate_of"]["activity_id"] == first.json()["activity_id"]

    def test_a_fresh_track_is_not_flagged(self, env):
        client, *_ = env
        assert _inspect(client).json()["duplicate_of"] is None


class TestImportTrustsTheFile:
    def test_a_recorded_track_needs_nothing_typed(self, env):
        """It knows when it happened, what it is called and what it was."""
        client, engine, *_ = env

        resp = _import(client)

        assert resp.status_code == 200, resp.text
        with Session(engine) as sess:
            row = sess.get(DBActivity, resp.json()["activity_id"])
        assert row.name == "Morning ride"
        assert row.type == "ride"
        assert row.start_date.startswith("2024-08-12T07:33")
        assert row.elapsed_time == 39

    def test_moving_time_comes_from_the_track(self, env):
        """It used to be set equal to elapsed time, so every import claimed it
        had never stopped."""
        client, engine, *_ = env
        content = _timed_track(count=40, step_m=0.05)     # barely moving

        resp = _import(client, content=content)

        with Session(engine) as sess:
            row = sess.get(DBActivity, resp.json()["activity_id"])
        assert row.elapsed_time == 39
        assert row.moving_time == 0, (
            "a track that never moved has no moving time, and saying so is the "
            "whole point — a zero must not be quietly replaced by the elapsed "
            "window"
        )

    def test_what_the_user_types_wins(self, env):
        client, engine, *_ = env

        resp = _import(client, date="2023-01-02", start_time="06:00",
                       end_time="07:30", activity_type="hike",
                       activity_name="Renamed by hand")

        with Session(engine) as sess:
            row = sess.get(DBActivity, resp.json()["activity_id"])
        assert row.name == "Renamed by hand"
        assert row.type == "hike"
        assert row.start_date.startswith("2023-01-02T06:00")
        assert row.elapsed_time == 5400

    def test_a_route_without_times_must_be_told_when_it_happened(self, env):
        client, *_ = env

        resp = _import(client, content=_route())

        assert resp.status_code == 422
        assert any("no timestamps" in e.lower()
                   for e in resp.json()["detail"]["errors"])

    def test_a_route_imports_once_it_has_a_date(self, env):
        client, engine, *_ = env

        resp = _import(client, content=_route(), date="2024-06-01",
                       start_time="09:00", end_time="10:00",
                       activity_type="ride")

        assert resp.status_code == 200, resp.text
        with Session(engine) as sess:
            row = sess.get(DBActivity, resp.json()["activity_id"])
        assert row.name == "Planned loop"

    def test_a_multi_track_file_still_needs_a_choice(self, env):
        """Quietly importing the first of several is the silent partial import
        issue #260 ruled out."""
        client, *_ = env

        resp = _import(client, content=_two_tracks())

        assert resp.status_code == 422
        assert any("choose which one" in e.lower()
                   for e in resp.json()["detail"]["errors"])

    def test_a_chosen_track_imports(self, env):
        client, engine, *_ = env

        resp = _import(client, content=_two_tracks(), track_index=1,
                       date="2024-06-01", start_time="09:00", end_time="10:00")

        assert resp.status_code == 200, resp.text
        with Session(engine) as sess:
            row = sess.get(DBActivity, resp.json()["activity_id"])
        assert row.name == "Lap 2"

    def test_an_oversized_file_is_refused_without_parsing(self, env):
        """The guard has to run before the parse: gpxpy's object tree is ten to
        fifteen times the bytes on the wire, so refusing afterwards has already
        cost the memory."""
        client, *_ = env
        padding = b"<!--" + b"x" * (13 * 1024 * 1024) + b"-->"

        resp = _import(client, content=_HEADER.encode() + padding + b"</gpx>")

        assert resp.status_code == 422
        assert any("limit is 12 MB" in e for e in resp.json()["detail"]["errors"])
