"""Data-migration test for b7f1a3c9d204 — recompute inflated elevation gain.

Builds a throwaway SQLite DB up to the revision *before* the backfill, seeds
activities covering every case the migration distinguishes, runs it, and asserts
who was corrected and who was left alone. Hermetic — never touches the
developer's real db.

The case that matters most is the encrypted one: `total_elevation_gain` is a
plain column, but the profile it must be recomputed from can be a client-side
E2EE envelope the server cannot decrypt. Those rows must come through untouched
rather than be zeroed or crash the migration (issue #260, follow-up #366).
"""
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, MetaData, Table, text

from models.project_db import DBActivity
from src.models.track_edit import elevation_gain

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PREV_REV = "43f9efcb0207"      # down_revision of the backfill
_BACKFILL_REV = "b7f1a3c9d204"

#: Inflated figure the old raw-delta-sum code would have stored.
_STORED_INFLATED = 4094.0


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "elev_backfill_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    return db_path


def _noisy_profile_json() -> str:
    """A 600 m climb under ±1.2 m of noise, stored the way the app stores it."""
    import random

    random.seed(7)
    n = 6000
    elevations = [
        200.0 + 600.0 * (1 - abs(2 * (i / (n - 1)) - 1)) + random.gauss(0, 1.2)
        for i in range(n)
    ]
    distances = [i * 0.01 for i in range(n)]
    return json.dumps({"distances_km": distances, "elevations_m": elevations})


def _seed_activity(engine, **kwargs) -> None:
    """Insert using only the columns that exist in `activity` AT _PREV_REV.

    Same idiom as test_migration_prune_orphaned_tails: the ORM class always
    reflects the CURRENT model, so filtering against the reflected table keeps
    this test immune to columns added after this migration.
    """
    obj = DBActivity(**kwargs)
    data = {k: v for k, v in obj.__dict__.items() if not k.startswith("_sa_")}
    tbl = Table("activity", MetaData(), autoload_with=engine)
    data = {k: v for k, v in data.items() if k in tbl.columns}
    with engine.begin() as conn:
        conn.execute(insert(tbl), data)


def _gains(engine) -> dict[int, float]:
    with engine.connect() as conn:
        return {
            r[0]: r[1]
            for r in conn.execute(text("SELECT id, total_elevation_gain FROM activity"))
        }


@pytest.fixture()
def seeded(db):
    """Four activities at _PREV_REV, one per case the migration distinguishes."""
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV_REV)
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    profile = _noisy_profile_json()
    common = dict(user_info_id=1, name="x", type="Ride",
                  total_elevation_gain=_STORED_INFLATED)

    # 1 — hand-edited Strava activity: ours to recompute.
    _seed_activity(engine, id=1, is_edited=True,
                   elevation_profile_json=profile, **common)
    # 2 — GPX import: also ours, even though it was never edited.
    _seed_activity(engine, id=-2, is_edited=False, source="gpx",
                   elevation_profile_json=profile, **common)
    # 3 — untouched Strava activity: its gain is Strava's, not ours.
    _seed_activity(engine, id=3, is_edited=False,
                   elevation_profile_json=profile, **common)
    # 4 — hand-edited, but the profile is an E2EE envelope the server cannot
    #     decrypt (`v1.<wrapped DEK>.<ciphertext>`).
    _seed_activity(engine, id=4, is_edited=True,
                   elevation_profile_json="v1.d3JhcHBlZA==.Y2lwaGVydGV4dA==",
                   **common)
    return cfg, engine, profile


def test_backfill_corrects_derived_gains_and_spares_the_rest(seeded):
    cfg, engine, profile = seeded
    expected = elevation_gain(json.loads(profile)["elevations_m"])

    command.upgrade(cfg, _BACKFILL_REV)
    gains = _gains(engine)

    assert gains[1] == pytest.approx(expected), "edited activity must be corrected"
    assert gains[-2] == pytest.approx(expected), "GPX import must be corrected"
    assert gains[1] == pytest.approx(600.0, abs=25.0), "and land on the real climb"
    assert gains[3] == pytest.approx(_STORED_INFLATED), (
        "an untouched Strava activity keeps the figure Strava gave us"
    )
    assert gains[4] == pytest.approx(_STORED_INFLATED), (
        "an E2EE-enveloped profile cannot be decrypted server-side, so the row "
        "must survive the migration untouched — not zeroed (see issue #366)"
    )


def test_backfill_is_idempotent(seeded):
    """Re-running recomputes the same values from the same stored profiles."""
    cfg, engine, _ = seeded
    command.upgrade(cfg, _BACKFILL_REV)
    before = _gains(engine)

    command.stamp(cfg, _PREV_REV)           # rewind bookkeeping only
    command.upgrade(cfg, _BACKFILL_REV)     # run the backfill again

    assert _gains(engine) == before


def test_unusable_profile_is_skipped_not_zeroed(db):
    """Malformed or too-short profiles leave the stored figure alone."""
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV_REV)
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    common = dict(user_info_id=1, name="x", type="Ride", is_edited=True,
                  total_elevation_gain=_STORED_INFLATED)
    _seed_activity(engine, id=10, elevation_profile_json="{not json", **common)
    _seed_activity(engine, id=11, elevation_profile_json=json.dumps(
        {"distances_km": [0.0], "elevations_m": [100.0]}), **common)

    command.upgrade(cfg, _BACKFILL_REV)

    gains = _gains(engine)
    assert gains[10] == pytest.approx(_STORED_INFLATED)
    assert gains[11] == pytest.approx(_STORED_INFLATED)
