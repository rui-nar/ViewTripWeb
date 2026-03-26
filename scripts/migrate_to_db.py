"""One-shot migration script: ingest all legacy .gettracks files into the DB.

Run from the repo root::

    python scripts/migrate_to_db.py

The script is idempotent — projects already in the DB are skipped.
After ingestion each file is renamed to ``*.gettracks.migrated`` so future
runs remain O(1).  The originals can be deleted once you're satisfied with
the migration.
"""
from __future__ import annotations

import os
import sys

# Ensure repo root is on sys.path so imports resolve correctly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reflex as rx  # noqa: E402  (must come after sys.path tweak)

# Import all SQLModel table models so SQLAlchemy's FK resolution works
from reflex_local_auth import LocalUser  # noqa: F401, E402
from reflex_local_auth.local_auth import LocalAuthSession  # noqa: F401, E402
from app.models.user import StravaToken, UserInfo  # noqa: F401, E402
from app.models.project_db import (  # noqa: F401, E402
    DBActivity, DBProject, DBProjectItem, DBStravaCache,
)
from src.project.project_repo import ProjectRepo  # noqa: E402

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_EXTENSION = ".gettracks"


def _find_legacy_files() -> list[tuple[int, str]]:
    """Yield (user_info_id, file_path) for every un-migrated .gettracks file."""
    users_dir = os.path.join(_DATA_DIR, "users")
    if not os.path.isdir(users_dir):
        return []
    results = []
    for uid_str in os.listdir(users_dir):
        try:
            user_info_id = int(uid_str)
        except ValueError:
            continue
        projects_dir = os.path.join(users_dir, uid_str, "projects")
        if not os.path.isdir(projects_dir):
            continue
        for fname in os.listdir(projects_dir):
            if fname.endswith(_EXTENSION):
                results.append((user_info_id, os.path.join(projects_dir, fname)))
    return results


def main() -> None:
    repo = ProjectRepo()
    files = _find_legacy_files()

    if not files:
        print("No legacy .gettracks files found.")
        return

    print(f"Found {len(files)} file(s) to migrate.")
    ok = skipped = errors = 0

    for user_info_id, path in files:
        name = os.path.basename(path)[: -len(_EXTENSION)]
        try:
            with rx.session() as sess:
                repo.ingest_gettracks(sess, user_info_id, path)
            print(f"  OK  user {user_info_id} / {name}")
            ok += 1
        except Exception as exc:
            print(f"  ERR user {user_info_id} / {name}: {exc}")
            errors += 1

    print(f"\nDone — {ok} migrated, {skipped} skipped, {errors} errors.")


if __name__ == "__main__":
    main()
