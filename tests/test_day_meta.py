"""Tests for day metadata serialisation, persistence, and the full-replace
contract that the update_day_meta endpoint relies on.

Background: a previous bug caused all day metadata to be silently overwritten
with empty {} entries.  The root cause was _autoFillDaysToToday() calling
saveDayMeta() with stale/empty data, which the backend stored as a full
replace.  The fix makes _autoFillDaysToToday() update only in-memory state.

These tests guard against regressions at three layers:
  1. DayMeta model — fields and defaults.
  2. ProjectIO.to_dict() — the REST serialisation emitted by GET /api/projects/{name}.
  3. Repo round-trip — save_project → get_project cycle preserves real data.
  4. Full-replace semantics — overwriting with empty entries loses real data
     (intentional: the client is responsible for never sending stale data).
"""

from __future__ import annotations

import json

import pytest

from src.models.project import DayMeta, Project
from src.project.project_io import ProjectIO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_with_day(date: str, **kwargs) -> Project:
    """Return a minimal Project with one DayMeta entry."""
    p = Project(name="test-trip")
    p.day_meta = {date: DayMeta(**kwargs)}
    return p


def _to_dict_day(p: Project, date: str) -> dict:
    return ProjectIO.to_dict(p)["day_meta"][date]


# ---------------------------------------------------------------------------
# 1. DayMeta model
# ---------------------------------------------------------------------------

class TestDayMetaModel:
    def test_all_fields_default_to_none_or_empty(self):
        dm = DayMeta()
        assert dm.difficulty is None
        assert dm.sleeping is None
        assert dm.weather is None
        assert dm.journal is None
        assert dm.tags == []
        assert dm.counters == {}

    def test_full_construction(self):
        dm = DayMeta(
            difficulty="hard",
            sleeping="tent",
            weather="heavy_rain",
            journal="Col du Galibier in a storm.",
            tags=["alpine", "snow"],
            counters={"km": 145.0, "ascent": 4200.0},
        )
        assert dm.difficulty == "hard"
        assert dm.sleeping == "tent"
        assert dm.weather == "heavy_rain"
        assert dm.journal == "Col du Galibier in a storm."
        assert dm.tags == ["alpine", "snow"]
        assert dm.counters["km"] == pytest.approx(145.0)
        assert dm.counters["ascent"] == pytest.approx(4200.0)


# ---------------------------------------------------------------------------
# 2. ProjectIO.to_dict() — REST serialisation
# ---------------------------------------------------------------------------

class TestProjectIODayMeta:
    def test_real_fields_appear_in_output(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", difficulty="hard", sleeping="hotel"),
            "2025-06-01",
        )
        assert d["difficulty"] == "hard"
        assert d["sleeping"] == "hotel"

    def test_none_fields_are_excluded(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01"),  # all defaults
            "2025-06-01",
        )
        assert "difficulty" not in d
        assert "sleeping" not in d
        assert "weather" not in d
        assert "journal" not in d

    def test_all_none_produces_empty_dict(self):
        """An empty DayMeta round-trips as {} in the API response."""
        d = _to_dict_day(_project_with_day("2025-06-01"), "2025-06-01")
        assert d == {}

    def test_tags_included_when_non_empty(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", tags=["border", "rain"]),
            "2025-06-01",
        )
        assert d["tags"] == ["border", "rain"]

    def test_tags_excluded_when_empty_list(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", tags=[]),
            "2025-06-01",
        )
        assert "tags" not in d

    def test_counters_included_when_non_empty(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", counters={"km": 95.5}),
            "2025-06-01",
        )
        assert d["counters"] == {"km": pytest.approx(95.5)}

    def test_counters_excluded_when_empty(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", counters={}),
            "2025-06-01",
        )
        assert "counters" not in d

    def test_journal_included(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", journal="Great day!"),
            "2025-06-01",
        )
        assert d["journal"] == "Great day!"

    def test_weather_included(self):
        d = _to_dict_day(
            _project_with_day("2025-06-01", weather="some_rain"),
            "2025-06-01",
        )
        assert d["weather"] == "some_rain"

    def test_multiple_dates_all_present(self):
        p = Project(name="t")
        p.day_meta = {
            "2025-06-01": DayMeta(difficulty="easy"),
            "2025-06-02": DayMeta(sleeping="camping"),
            "2025-06-03": DayMeta(),
        }
        result = ProjectIO.to_dict(p)["day_meta"]
        assert "2025-06-01" in result
        assert "2025-06-02" in result
        assert "2025-06-03" in result
        assert result["2025-06-01"]["difficulty"] == "easy"
        assert result["2025-06-02"]["sleeping"] == "camping"
        assert result["2025-06-03"] == {}


# ---------------------------------------------------------------------------
# 3. Repo day_meta JSON parsing — the exact logic in _row_to_project
# ---------------------------------------------------------------------------

class TestDayMetaParsing:
    """Tests the parsing code in _row_to_project without a live database.

    _row_to_project() deserialises day_meta_json into DayMeta objects.
    This logic is the read-path: if it silently loses fields, every load
    would show empty metadata even if the database contains real data.
    """

    def _parse(self, day_meta_json: str) -> dict[str, DayMeta]:
        """Replicate the exact parsing fragment from project_repo._row_to_project."""
        raw_dm = json.loads(day_meta_json or "{}")
        return {
            dk: DayMeta(
                difficulty=v.get("difficulty"),
                sleeping=v.get("sleeping"),
                weather=v.get("weather"),
                journal=v.get("journal"),
                tags=v.get("tags") or [],
                counters={k: float(cv) for k, cv in (v.get("counters") or {}).items()},
            )
            for dk, v in raw_dm.items()
        }

    def test_full_entry_parses_all_fields(self):
        raw = json.dumps({
            "2025-06-01": {
                "difficulty": "super_hard",
                "sleeping": "bivouac",
                "weather": "heavy_rain",
                "journal": "Brutal day.",
                "tags": ["snow", "heatwave"],
                "counters": {"km": 120.5, "ascent": 3200.0},
            }
        })
        result = self._parse(raw)
        dm = result["2025-06-01"]
        assert dm.difficulty == "super_hard"
        assert dm.sleeping == "bivouac"
        assert dm.weather == "heavy_rain"
        assert dm.journal == "Brutal day."
        assert dm.tags == ["snow", "heatwave"]
        assert dm.counters["km"] == pytest.approx(120.5)
        assert dm.counters["ascent"] == pytest.approx(3200.0)

    def test_empty_dict_entry_gives_all_none(self):
        """The {} entries that _autoFillDaysToToday used to persist
        deserialise to all-None DayMeta — confirming data is invisible to stats."""
        result = self._parse(json.dumps({"2025-06-01": {}}))
        dm = result["2025-06-01"]
        assert dm.difficulty is None
        assert dm.sleeping is None
        assert dm.weather is None
        assert dm.journal is None
        assert dm.tags == []
        assert dm.counters == {}

    def test_missing_fields_default_to_none(self):
        result = self._parse(json.dumps({"2025-06-01": {"difficulty": "easy"}}))
        dm = result["2025-06-01"]
        assert dm.difficulty == "easy"
        assert dm.sleeping is None

    def test_empty_json_gives_empty_dict(self):
        assert self._parse("{}") == {}

    def test_null_json_gives_empty_dict(self):
        assert self._parse(None) == {}  # noqa: simulates getattr returning None


# ---------------------------------------------------------------------------
# 4. Repository round-trip — save_project → get_project
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_db(monkeypatch):
    """Spin up an isolated in-memory SQLite database for one test.

    Patches models.db.engine so all repo calls go to this throwaway DB.
    Yields (repo, session, user_id).
    """
    import models.db as db_module
    from sqlmodel import Session, SQLModel, create_engine

    from models.user import UserInfo  # noqa: ensures table registered
    from models.project_db import DBProject, DBProjectItem  # noqa
    from src.project.project_repo import ProjectRepo

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as sess:
        user = UserInfo(display_name="Test User", email="test@example.com")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        user_id = user.id

    repo = ProjectRepo()
    with Session(test_engine) as sess:
        yield repo, sess, user_id


class TestDayMetaRepoRoundTrip:
    def test_full_metadata_survives_round_trip(self, repo_db):
        repo, sess, uid = repo_db
        p = Project(name="velodyssee")
        p.day_meta = {
            "2023-07-14": DayMeta(
                difficulty="hard",
                sleeping="bivouac",
                weather="clear",
                journal="Bastille Day on the road.",
                tags=["rest-day", "market"],
                counters={"km": 142.0},
            ),
        }
        repo.save_project(sess, uid, p)

        loaded = repo.get_project(sess, uid, "velodyssee")
        assert loaded is not None
        dm = loaded.day_meta["2023-07-14"]
        assert dm.difficulty == "hard"
        assert dm.sleeping == "bivouac"
        assert dm.weather == "clear"
        assert dm.journal == "Bastille Day on the road."
        assert dm.tags == ["rest-day", "market"]
        assert dm.counters["km"] == pytest.approx(142.0)

    def test_multiple_dates_all_preserved(self, repo_db):
        repo, sess, uid = repo_db
        p = Project(name="trip")
        p.day_meta = {
            "2025-06-01": DayMeta(difficulty="easy"),
            "2025-06-02": DayMeta(sleeping="hotel", tags=["city"]),
            "2025-06-03": DayMeta(),  # intentionally empty
        }
        repo.save_project(sess, uid, p)

        loaded = repo.get_project(sess, uid, "trip")
        assert loaded.day_meta["2025-06-01"].difficulty == "easy"
        assert loaded.day_meta["2025-06-02"].sleeping == "hotel"
        assert loaded.day_meta["2025-06-02"].tags == ["city"]
        assert "2025-06-03" in loaded.day_meta

    def test_full_replace_semantics_overwrite_drops_old_dates(self, repo_db):
        """save_project is a full replace of day_meta_json.

        Saving with a subset of dates does NOT preserve dates omitted from
        the new payload.  This is intentional: the client always sends the
        full map; orphan trimming (e.g. the trip-end cutoff) relies on this.
        """
        repo, sess, uid = repo_db
        p = Project(name="trip")
        p.day_meta = {
            "2025-06-01": DayMeta(difficulty="hard"),
            "2025-06-02": DayMeta(difficulty="easy"),
        }
        repo.save_project(sess, uid, p)

        # Second save omits 2025-06-01 entirely
        p2 = Project(name="trip")
        p2.day_meta = {"2025-06-02": DayMeta(difficulty="super_hard")}
        repo.save_project(sess, uid, p2)

        loaded = repo.get_project(sess, uid, "trip")
        assert "2025-06-01" not in loaded.day_meta  # removed by full replace
        assert loaded.day_meta["2025-06-02"].difficulty == "super_hard"

    def test_saving_only_empty_entries_wipes_real_data(self, repo_db):
        """Critical regression guard: the scenario that caused the data loss.

        If real metadata is replaced by a payload containing only {} entries
        (the shape _autoFillDaysToToday used to produce), the real data is
        gone.  _autoFillDaysToToday no longer calls saveDayMeta, so this
        cannot happen via the auto-fill path — but this test ensures the
        full-replace contract stays visible and any future code that writes
        to the day-meta endpoint must send complete data.
        """
        repo, sess, uid = repo_db

        # Step 1: write real metadata
        p = Project(name="trip")
        p.day_meta = {
            "2025-06-01": DayMeta(difficulty="hard", sleeping="tent"),
            "2025-06-02": DayMeta(difficulty="easy", weather="clear"),
        }
        repo.save_project(sess, uid, p)

        # Verify it's there
        loaded = repo.get_project(sess, uid, "trip")
        assert loaded.day_meta["2025-06-01"].difficulty == "hard"

        # Step 2: save only empty {} entries (the old bug scenario)
        p_empty = Project(name="trip")
        p_empty.day_meta = {
            "2025-06-01": DayMeta(),
            "2025-06-02": DayMeta(),
        }
        repo.save_project(sess, uid, p_empty)

        # Step 3: real data is gone — full replace semantics
        clobbered = repo.get_project(sess, uid, "trip")
        dm1 = clobbered.day_meta["2025-06-01"]
        assert dm1.difficulty is None, (
            "Real metadata was overwritten by empty entries — "
            "the client must never send stale/empty data to update_day_meta"
        )
        assert dm1.sleeping is None
        dm2 = clobbered.day_meta["2025-06-02"]
        assert dm2.difficulty is None
        assert dm2.weather is None

    def test_counters_and_sleeping_options_round_trip(self, repo_db):
        repo, sess, uid = repo_db
        repo.create_project(sess, uid, "trip")  # creates with defaults

        p = repo.get_project(sess, uid, "trip")
        p.day_meta = {"2025-06-01": DayMeta(counters={"km": 80.0, "climbing": 1500.0})}
        p.sleeping_options = ["Camping", "Hotel", "Friend"]
        repo.save_project(sess, uid, p)

        loaded = repo.get_project(sess, uid, "trip")
        assert loaded.day_meta["2025-06-01"].counters["km"] == pytest.approx(80.0)
        assert loaded.day_meta["2025-06-01"].counters["climbing"] == pytest.approx(1500.0)
        assert "Camping" in loaded.sleeping_options
        assert "Hotel" in loaded.sleeping_options
