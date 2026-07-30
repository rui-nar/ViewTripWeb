"""Item write granularity and write-path contention (issue #173, phase A).

Two write paths reach ``projectitem``:

* the whole-list rewrite (``save_project`` → ``_replace_items``), and
* direct row inserts (``api/memories.py``, ``api/journal.py``,
  ``api/encounters.py``), which shift positions and add a row without going
  through ``save_project``.

These raced. A direct insert that committed after a structural mutation loaded
its snapshot was silently erased by that mutation's rewrite, because the insert
never advanced ``lock_version`` and the rewrite did not check it. Fixing it took
both halves: :func:`bump_lock_version` on the insert side, and a version-checked
save behind :meth:`save_project_with_retry` on the rewrite side.

The interleaving is pinned deterministically rather than raced with threads —
the ordering is what matters, not the concurrency primitive.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from models.project_db import DBActivity, DBEncounter, DBProject, DBProjectItem
from models.user import UserInfo
from src.project.project_repo import ProjectRepo, StaleWriteError, bump_lock_version

_repo = ProjectRepo()


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", eng)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def seeded(engine):
    """A project with two activity items at positions 0 and 1."""
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        for i, act_id in enumerate((111, 222)):
            sess.add(DBActivity(
                id=act_id, user_info_id=u.id, name=f"Ride {i}", type="Ride",
                distance=1000.0, moving_time=100, elapsed_time=120,
                total_elevation_gain=0.0,
                start_date_local="2024-06-01T09:00:00Z",
                start_latlng_json=json.dumps([48.0, 2.0]),
                end_latlng_json=json.dumps([48.5, 2.5]),
            ))
            sess.add(DBProjectItem(project_id=proj.id, position=i,
                                   item_type="activity", activity_id=act_id))
        sess.commit()
        return u.id, proj.id


def _item_types(engine, project_id):
    with Session(engine) as sess:
        rows = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
    return [r.item_type for r in rows]


def _insert_encounter_item(engine, project_id, position):
    """Mirror the direct-insert path of api/encounters.py:167-190.

    Reproduced rather than called so the test stays independent of the
    encounters router's request plumbing, but it must stay in step with it —
    including the ``bump_lock_version`` that makes the insert visible to the CAS.
    """
    with Session(engine) as sess:
        enc = DBEncounter(project_id=project_id, date="2024-06-01")
        sess.add(enc); sess.commit(); sess.refresh(enc)
        existing = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        for item in existing:
            if item.position >= position:
                item.position += 1
                sess.add(item)
        sess.add(DBProjectItem(project_id=project_id, position=position,
                               item_type="encounter", encounter_id=enc.id))
        bump_lock_version(sess, project_id)
        sess.commit()


class TestDirectInsertVisibleToTheLock:
    def test_insert_advances_lock_version(self, engine, seeded):
        """Without this the CAS cannot see the insert at all."""
        _user_id, project_id = seeded
        with Session(engine) as sess:
            before = sess.get(DBProject, project_id).lock_version

        _insert_encounter_item(engine, project_id, position=1)

        with Session(engine) as sess:
            assert sess.get(DBProject, project_id).lock_version == before + 1


class TestDirectInsertVsRewrite:
    def test_stale_rewrite_is_rejected_not_silently_applied(self, engine, seeded):
        user_id, project_id = seeded

        # 1. A structural mutation loads its snapshot (two activity items).
        with Session(engine) as sess:
            snapshot = _repo.get_project(sess, user_id, "Trip")
        assert len(snapshot.items) == 2

        # 2. A concurrent request inserts an encounter item and commits.
        _insert_encounter_item(engine, project_id, position=1)
        assert _item_types(engine, project_id) == ["activity", "encounter", "activity"]

        # 3. Saving the stale snapshot must be refused rather than rewriting
        #    the encounter out of existence.
        with Session(engine) as sess:
            with pytest.raises(StaleWriteError):
                _repo.save_project(sess, user_id, snapshot, check_version=True)

        assert _item_types(engine, project_id) == ["activity", "encounter", "activity"]

    def test_retry_helper_reapplies_onto_reloaded_state(self, engine, seeded):
        """The retry path re-runs the mutation against freshly loaded state."""
        user_id, project_id = seeded
        _insert_encounter_item(engine, project_id, position=1)

        def _reverse(project):
            project.items.reverse()

        saved = _repo.save_project_with_retry(user_id, "Trip", _reverse)

        assert saved is not None
        # All three items survive, in reversed order — the encounter was never lost.
        assert _item_types(engine, project_id) == ["activity", "encounter", "activity"]
        assert [i.item_type for i in saved.items] == ["activity", "encounter", "activity"]

    def test_retry_helper_returns_none_for_a_missing_project(self, engine, seeded):
        user_id, _project_id = seeded
        assert _repo.save_project_with_retry(user_id, "No Such Trip", lambda p: None) is None

    def test_retry_helper_gives_up_and_raises_when_every_attempt_loses(
            self, engine, seeded, monkeypatch):
        """Exhaustion surfaces as StaleWriteError — the caller decides what it means."""
        user_id, project_id = seeded

        def _always_conflict(*_a, **_kw):
            raise StaleWriteError("forced")

        monkeypatch.setattr(ProjectRepo, "save_project", _always_conflict)
        with pytest.raises(StaleWriteError):
            _repo.save_project_with_retry(user_id, "Trip", lambda p: None, attempts=3)

    def test_retry_helper_reloads_between_attempts(self, engine, seeded, monkeypatch):
        """A retry must re-read; re-applying to the rejected snapshot drops work."""
        user_id, _project_id = seeded
        loads: list[int] = []
        real_get = ProjectRepo.get_project

        def _counting_get(self, sess, uid, name, **kw):
            project = real_get(self, sess, uid, name, **kw)
            loads.append(id(project))
            return project

        calls = {"n": 0}
        real_save = ProjectRepo.save_project

        def _fail_once(self, sess, uid, project, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise StaleWriteError("first attempt loses")
            return real_save(self, sess, uid, project, **kw)

        monkeypatch.setattr(ProjectRepo, "get_project", _counting_get)
        monkeypatch.setattr(ProjectRepo, "save_project", _fail_once)

        _repo.save_project_with_retry(user_id, "Trip", lambda p: None, attempts=3)

        assert calls["n"] == 2, "expected exactly one retry"
        assert len(loads) == 2, "each attempt must load its own project"
        assert loads[0] != loads[1], "the retry re-used the stale object"


class TestFilteredViewIsNotSaveable:
    """A per-user journal load hides other users' timeline items (issue #106).

    ``save_project`` rewrites the item list from ``project.items``, so saving
    such a view would delete the rows it was never given. Every caller is
    read-only today; the guard keeps a future one from silently losing data.
    """

    def test_a_filtered_load_is_marked_partial(self, engine, seeded):
        user_id, _project_id = seeded
        with Session(engine) as sess:
            whole = _repo.get_project(sess, user_id, "Trip")
            view = _repo.get_project(sess, user_id, "Trip", journal_user_id=user_id)
        assert whole.partial_items is False
        assert view.partial_items is True

    def test_saving_a_filtered_view_is_refused(self, engine, seeded):
        user_id, project_id = seeded
        with Session(engine) as sess:
            view = _repo.get_project(sess, user_id, "Trip", journal_user_id=user_id)

        with Session(engine) as sess:
            with pytest.raises(ValueError, match="filtered view"):
                _repo.save_project(sess, user_id, view)

        # Refused before any write — the timeline is untouched.
        assert _item_types(engine, project_id) == ["activity", "activity"]

    def test_the_retry_helper_refuses_it_too(self, engine, seeded):
        """save_project_with_retry loads unfiltered, so it stays usable."""
        user_id, _project_id = seeded
        saved = _repo.save_project_with_retry(user_id, "Trip", lambda p: None)
        assert saved is not None and saved.partial_items is False
