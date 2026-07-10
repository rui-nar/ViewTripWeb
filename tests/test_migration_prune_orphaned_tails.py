"""Data-migration test for d5b1c0a2e3f4 — prune orphaned split-tail activities.

Builds a throwaway SQLite DB up to the revision *before* the prune, seeds a mix
of activity rows (orphaned local, referenced local, referenced Strava, orphaned
Strava), runs the prune migration, and asserts only the orphaned LOCAL row is
gone. Hermetic — never touches the developer's real db.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlmodel import Session

from models.project_db import DBActivity, DBProjectItem

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PREV_REV = "f40e0c0de001"   # down_revision of the prune migration
_PRUNE_REV = "d5b1c0a2e3f4"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "prune_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    return db_path


def _activity_ids(engine) -> set[int]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT id FROM activity"))}


def test_prune_removes_only_orphaned_local_rows(db):
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV_REV)

    engine = create_engine(f"sqlite:///{db.as_posix()}")
    # Seed via the ORM so all NOT NULL activity columns get their model defaults.
    # SQLite leaves FK enforcement off, so activity/projectitem rows stand alone
    # without userinfo/project parents — keeps the fixture focused on the two
    # tables the prune actually reads.
    with Session(engine) as s:
        # Four activities: only the orphaned LOCAL one (-1) must be pruned.
        for aid in (-1, -2, 100, 200):
            s.add(DBActivity(id=aid, user_info_id=1, name="x", type="Ride"))
        # -2 (local) and 100 (Strava) are referenced by a timeline item; -1 and
        # 200 are orphaned. The prune is scoped to id < 0, so 200 survives too.
        s.add(DBProjectItem(project_id=1, position=0, item_type="activity", activity_id=-2))
        s.add(DBProjectItem(project_id=1, position=1, item_type="activity", activity_id=100))
        s.commit()

    command.upgrade(cfg, _PRUNE_REV)

    assert _activity_ids(engine) == {-2, 100, 200}, (
        "prune must delete only the orphaned negative-id row (-1), never a "
        "referenced row (-2, 100) nor any positive id (200)"
    )


def test_prune_is_noop_on_clean_db(db):
    """Idempotent: re-running the prune on an already-clean DB changes nothing."""
    cfg = _cfg(db)
    command.upgrade(cfg, "head")            # includes the prune
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    before = _activity_ids(engine)
    command.stamp(cfg, _PREV_REV)           # rewind bookkeeping only
    command.upgrade(cfg, _PRUNE_REV)        # run the prune again
    assert _activity_ids(engine) == before
