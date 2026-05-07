"""One-shot migration script: ingest all legacy .gettracks files into the DB.

Run from the repo root::

    python scripts/migrate_to_db.py

The script is idempotent — projects already in the DB are skipped.
After ingestion each file is renamed to ``*.migrated`` so future
runs remain O(1).  The originals can be deleted once you're satisfied with
the migration.
"""
from __future__ import annotations

import os
import sys

# Ensure repo root is on sys.path so imports resolve correctly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all SQLModel table models so SQLAlchemy's FK resolution works
from models.user import LocalUser, StravaToken, UserInfo  # noqa: F401, E402
from models.project_db import (  # noqa: F401, E402
    DBActivity, DBProject, DBProjectItem, DBStravaCache,
)
from models.db import get_session  # noqa: E402
from src.project.project_repo import ProjectRepo  # noqa: E402

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_EXTENSIONS = (".viewtrip", ".gettracks")


def _find_legacy_files() -> list[tuple[int, str]]:
    """Yield (user_info_id, file_path) for every un-migrated project file."""
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
            if any(fname.endswith(ext) for ext in _EXTENSIONS):
                results.append((user_info_id, os.path.join(projects_dir, fname)))
    return results


def main() -> None:
    repo = ProjectRepo()
    files = _find_legacy_files()

    if not files:
        print("No legacy project files found.")
        return

    print(f"Found {len(files)} file(s) to migrate.")
    ok = skipped = errors = 0

    for user_info_id, path in files:
        ext = next(e for e in _EXTENSIONS if path.endswith(e))
        name = os.path.basename(path)[: -len(ext)]
        try:
            with get_session() as sess:
                repo.ingest_project(sess, user_info_id, path)
            print(f"  OK  user {user_info_id} / {name}")
            ok += 1
        except Exception as exc:
            print(f"  ERR user {user_info_id} / {name}: {exc}")
            errors += 1

    print(f"\nDone — {ok} migrated, {skipped} skipped, {errors} errors.")


if __name__ == "__main__":
    main()
