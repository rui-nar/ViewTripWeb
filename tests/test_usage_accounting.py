"""Per-user storage counters used by quota checks (issue #121).

The counter is maintained incrementally on every write and delete, so the tests
that matter are the ones about it *drifting*: a double delete must not push it
negative, and the nightly reconcile must bring it back to what is on disk.
"""
from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
import src.admin.storage as storage_mod
from models.billing import UserUsage
from models.user import UserInfo
from src.billing.usage import (
    bytes_of,
    reconcile_all_usage,
    reconcile_usage,
    record_delta,
    record_written,
    unlink_and_record,
)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(storage_mod, "_DATA_DIR", str(tmp_path))
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as sess:
        sess.add(UserInfo(id=1, email="a@example.com", display_name="A"))
        sess.add(UserInfo(id=2, email="b@example.com", display_name="B"))
        sess.commit()
    yield test_engine


def _usage(engine, user_id: int) -> int:
    with Session(engine) as sess:
        row = sess.exec(
            select(UserUsage).where(UserUsage.user_info_id == user_id)
        ).first()
        return row.storage_bytes if row else 0


def _user_file(tmp_path, user_id: int, name: str, size: int):
    directory = tmp_path / "users" / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"x" * size)
    return path


class TestRecordDelta:
    def test_first_delta_creates_the_row(self, engine):
        record_delta(1, 500)
        assert _usage(engine, 1) == 500

    def test_deltas_accumulate(self, engine):
        record_delta(1, 500)
        record_delta(1, 250)
        assert _usage(engine, 1) == 750

    def test_negative_delta_subtracts(self, engine):
        record_delta(1, 500)
        record_delta(1, -200)
        assert _usage(engine, 1) == 300

    def test_counter_never_goes_negative(self, engine):
        """A double-counted delete must not hand the account infinite headroom."""
        record_delta(1, 100)
        record_delta(1, -500)
        assert _usage(engine, 1) == 0

    def test_zero_delta_writes_nothing(self, engine):
        record_delta(1, 0)
        assert _usage(engine, 1) == 0

    def test_users_are_independent(self, engine):
        record_delta(1, 100)
        record_delta(2, 700)
        assert (_usage(engine, 1), _usage(engine, 2)) == (100, 700)

    def test_accounting_failure_never_propagates(self, engine, monkeypatch):
        """An upload that already hit disk must not 500 because of bookkeeping."""
        def _boom():
            raise RuntimeError("db down")
        monkeypatch.setattr("src.billing.usage.get_session", _boom)
        record_delta(1, 100)  # must not raise


class TestFileHelpers:
    def test_bytes_of_sums_existing_files(self, tmp_path):
        a = tmp_path / "a.jpg"; a.write_bytes(b"x" * 10)
        b = tmp_path / "b.jpg"; b.write_bytes(b"x" * 5)
        assert bytes_of(a, b) == 15

    def test_bytes_of_skips_missing_files(self, tmp_path):
        a = tmp_path / "a.jpg"; a.write_bytes(b"x" * 10)
        assert bytes_of(a, tmp_path / "gone.jpg") == 10

    def test_record_written_counts_what_landed_on_disk(self, engine, tmp_path):
        full = _user_file(tmp_path, 1, "photo.jpg", 900)
        thumb = _user_file(tmp_path, 1, "photo_thumb.jpg", 100)
        record_written(1, full, thumb)
        assert _usage(engine, 1) == 1000

    def test_unlink_and_record_removes_files_and_subtracts(self, engine, tmp_path):
        full = _user_file(tmp_path, 1, "photo.jpg", 900)
        thumb = _user_file(tmp_path, 1, "photo_thumb.jpg", 100)
        record_written(1, full, thumb)
        unlink_and_record(1, [full, thumb])
        assert not full.exists() and not thumb.exists()
        assert _usage(engine, 1) == 0

    def test_deleting_an_already_missing_file_costs_nothing(self, engine, tmp_path):
        record_delta(1, 500)
        unlink_and_record(1, [tmp_path / "users" / "1" / "gone.jpg"])
        assert _usage(engine, 1) == 500


class TestReconcile:
    def test_corrects_a_drifted_counter(self, engine, tmp_path):
        _user_file(tmp_path, 1, "photo.jpg", 700)
        record_delta(1, 99999)  # drift: e.g. a delete that never got counted
        assert reconcile_usage(1) == 700
        assert _usage(engine, 1) == 700

    def test_counts_nested_directories(self, engine, tmp_path):
        nested = tmp_path / "users" / "1" / "memories" / "5"
        nested.mkdir(parents=True)
        (nested / "a.jpg").write_bytes(b"x" * 300)
        (nested / "a_thumb.jpg").write_bytes(b"x" * 50)
        assert reconcile_usage(1) == 350

    def test_a_user_with_no_files_reconciles_to_zero(self, engine):
        record_delta(1, 1234)
        assert reconcile_usage(1) == 0

    def test_reconcile_all_is_a_no_op_when_billing_is_off(self, engine, tmp_path,
                                                          monkeypatch):
        monkeypatch.delenv("BILLING_ENABLED", raising=False)
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        _user_file(tmp_path, 1, "photo.jpg", 700)
        reconcile_all_usage()
        assert _usage(engine, 1) == 0

    def test_reconcile_all_walks_every_user_when_billing_is_on(
        self, engine, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BILLING_ENABLED", "1")
        _user_file(tmp_path, 1, "photo.jpg", 700)
        _user_file(tmp_path, 2, "photo.jpg", 200)
        reconcile_all_usage()
        assert (_usage(engine, 1), _usage(engine, 2)) == (700, 200)
