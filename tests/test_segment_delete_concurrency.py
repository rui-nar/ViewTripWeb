"""Concurrent segment deletes must not fight over the project-wide lock.

Deleting a segment used to load the whole project, filter the item out of
``project.items`` and write the list back with ``save_project(check_version=
True)``. Two deletes issued milliseconds apart — which is the normal case, the
client fires one request per segment as each undo window expires — both read the
same ``lock_version``, so whichever committed second lost its CAS and got a 409.
Production, val stack::

    15:35:37,938  DELETE .../segments/f515ba6a-…  409   <- lost
    15:35:37,940  DELETE .../segments/24ee566f-…  204   <- won

The client had already removed both segments locally and never surfaced the
error, so the loser silently came back at the next full reload.

The fix is the same one issue #173 applied to route resolution: address the one
row instead of rewriting the whole item list, so two deletes of two different
segments touch two different rows and cannot fail each other.

Deleting a row without renumbering leaves a gap in ``position``, which the
direct-insert paths (memories/journal/encounters) used to paper over by treating
a list index and a position value as the same number. ``TestPositionGap`` pins
the translation that keeps them apart.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.encounters import router as encounters_router
from api.project_access import row_position_for_index
from api.segments import router as segments_router
from models.project_db import DBPerson, DBProject, DBProjectItem
from models.user import UserInfo
from src.project.project_repo import ProjectRepo

_repo = ProjectRepo()


def _segment_body(**overrides) -> dict:
    body = {
        "segment_type": "flight",
        "label": "SFO -> JFK",
        "start_lat": 37.6,
        "start_lon": -122.4,
        "end_lat": 40.6,
        "end_lon": -73.8,
    }
    body.update(overrides)
    return body


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        person = DBPerson(project_id=proj.id, name="Alice")
        sess.add(person); sess.commit(); sess.refresh(person)
        uid, pid, person_id = u.id, proj.id, person.id

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(segments_router)
    # The encounter route inserts an item row directly, without save_project —
    # the path that has to cope with the gap a single-row delete leaves.
    app.include_router(encounters_router)
    return TestClient(app), engine, uid, pid, person_id


def _create_segment(client, label: str) -> str:
    resp = client.post("/api/projects/My Trip/segments", json=_segment_body(label=label))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _positions(engine, project_id) -> list[int]:
    with Session(engine) as sess:
        return [
            r.position for r in sess.exec(
                select(DBProjectItem)
                .where(DBProjectItem.project_id == project_id)
                .order_by(DBProjectItem.position)
            ).all()
        ]


def _segment_ids(engine, uid) -> list[str]:
    with Session(engine) as sess:
        project = _repo.get_project(sess, uid, "My Trip")
    return [i.segment.id for i in project.items if i.item_type == "segment"]


class TestConcurrentDeletes:
    def test_a_sibling_delete_committing_mid_request_no_longer_409s(self, env, monkeypatch):
        """THE regression test for the production 409.

        The interleaving is pinned rather than raced: the concurrent sibling
        delete is injected into the *read* the old implementation performed
        between resolving the project and saving it back, which is the only
        window in which the conflict could arise. The fix closes that window by
        not reading the project at all, so on fixed code the hook never fires —
        ``test_delete_does_not_load_the_whole_project`` asserts that directly,
        so the pair cannot both pass vacuously.
        """
        client, engine, uid, _pid, _person_id = env
        keep_id = _create_segment(client, "kept")
        sibling_id = _create_segment(client, "sibling")
        target_id = _create_segment(client, "target")

        fired = {"n": 0}
        real_get_project = ProjectRepo.get_project

        def _sibling_deletes_first(self, sess, user_id, name, **kw):
            project = real_get_project(self, sess, user_id, name, **kw)
            if fired["n"] == 0:
                # The other in-flight DELETE finishes here — after this request
                # captured its lock_version, before it writes.
                fired["n"] += 1
                with Session(engine) as other:
                    theirs = real_get_project(self, other, user_id, name)
                    theirs.items = [
                        i for i in theirs.items
                        if not (i.item_type == "segment" and i.segment
                                and i.segment.id == sibling_id)
                    ]
                    self.save_project(other, user_id, theirs, check_version=True)
            return project

        monkeypatch.setattr(ProjectRepo, "get_project", _sibling_deletes_first)

        resp = client.delete(f"/api/projects/My Trip/segments/{target_id}")

        assert resp.status_code == 204, resp.text
        monkeypatch.undo()
        remaining = _segment_ids(engine, uid)
        assert target_id not in remaining, "the delete reported success but did nothing"
        assert keep_id in remaining

    def test_delete_does_not_load_the_whole_project(self, env, monkeypatch):
        """No load means no read-modify-write window means nothing to lose."""
        client, _engine, _uid, _pid, _person_id = env
        seg_id = _create_segment(client, "target")

        loads: list[str] = []
        real_get_project = ProjectRepo.get_project

        def _counting(self, sess, user_id, name, **kw):
            loads.append(name)
            return real_get_project(self, sess, user_id, name, **kw)

        monkeypatch.setattr(ProjectRepo, "get_project", _counting)
        assert client.delete(f"/api/projects/My Trip/segments/{seg_id}").status_code == 204
        assert loads == []

    def test_delete_still_advances_the_lock_version(self, env):
        """A structural writer that loaded first must still be told (issue #173)."""
        client, engine, _uid, pid, _person_id = env
        seg_id = _create_segment(client, "target")
        with Session(engine) as sess:
            before = sess.get(DBProject, pid).lock_version

        assert client.delete(f"/api/projects/My Trip/segments/{seg_id}").status_code == 204

        with Session(engine) as sess:
            assert sess.get(DBProject, pid).lock_version == before + 1

    def test_deleting_an_unknown_segment_is_still_a_404(self, env):
        client, engine, _uid, pid, _person_id = env
        _create_segment(client, "kept")

        assert client.delete("/api/projects/My Trip/segments/nope").status_code == 404

        with Session(engine) as sess:
            # A 404 must not have advanced the lock or touched a row.
            assert sess.get(DBProject, pid).lock_version is not None
        assert len(_positions(engine, pid)) == 1


class TestPositionGap:
    """A single-row delete leaves ``position`` sparse; inserts must cope."""

    def test_delete_leaves_the_surviving_positions_alone(self, env):
        client, engine, _uid, pid, _person_id = env
        ids = [_create_segment(client, f"s{i}") for i in range(4)]
        assert _positions(engine, pid) == [0, 1, 2, 3]

        assert client.delete(f"/api/projects/My Trip/segments/{ids[1]}").status_code == 204

        assert _positions(engine, pid) == [0, 2, 3]

    def test_ordering_survives_the_gap(self, env):
        client, engine, uid, _pid, _person_id = env
        ids = [_create_segment(client, f"s{i}") for i in range(4)]

        assert client.delete(f"/api/projects/My Trip/segments/{ids[1]}").status_code == 204

        assert _segment_ids(engine, uid) == [ids[0], ids[2], ids[3]]

    def test_creating_a_segment_renumbers_densely_again(self, env):
        """``create_segment`` goes through ``save_project``, which renumbers."""
        client, engine, _uid, pid, _person_id = env
        ids = [_create_segment(client, f"s{i}") for i in range(3)]
        client.delete(f"/api/projects/My Trip/segments/{ids[0]}")
        assert _positions(engine, pid) == [1, 2]

        _create_segment(client, "fresh")

        assert _positions(engine, pid) == [0, 1, 2]

    def test_an_encounter_still_lands_where_asked_across_a_gap(self, env):
        """The direct-insert path (no save_project) against sparse positions.

        Before the translation, ``insert_after_index`` was used as a position
        value: with positions [0, 2, 3] an append took position 3 and landed
        *before* the last row, and an insert after list index 1 took position 2
        and landed before its anchor instead of after it.
        """
        client, engine, uid, _pid, person_id = env
        ids = [_create_segment(client, f"s{i}") for i in range(4)]
        assert client.delete(f"/api/projects/My Trip/segments/{ids[1]}").status_code == 204

        # (insert_after_index, list index it must land at) — the second runs
        # against the list the first one left, hence index 4.
        for insert_after_index, expected_at in ((1, 2), (None, 4)):
            body = {"project_name": "My Trip", "person_id": person_id,
                    "date": "2024-06-01"}
            if insert_after_index is not None:
                body["insert_after_index"] = insert_after_index
            resp = client.post("/api/encounters/", json=body)
            assert resp.status_code == 201, resp.text

            with Session(engine) as sess:
                project = _repo.get_project(sess, uid, "My Trip")
            types = [i.item_type for i in project.items]
            assert types[expected_at] == "encounter", types

    @pytest.mark.parametrize(
        "positions, index, expected",
        [
            ([0, 1, 2], 0, 0),
            ([0, 1, 2], 3, 3),      # append onto dense positions
            ([0, 1, 3, 4], 2, 3),   # the gap: list index 2 is position 3
            ([0, 1, 3, 4], 4, 5),   # append past a gap must clear the last row
            ([], 0, 0),
        ],
    )
    def test_row_position_for_index(self, positions, index, expected):
        rows = [DBProjectItem(project_id=1, position=p, item_type="activity")
                for p in positions]
        assert row_position_for_index(rows, index) == expected
