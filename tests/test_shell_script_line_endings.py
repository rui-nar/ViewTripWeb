"""Shell scripts shipped in the image must be LF, not CRLF (issue #185).

`worker-entrypoint.sh` was checked out with CRLF on the Windows dev machine
(core.autocrlf=true), and deploy.ps1 builds the :validation image from the
working tree. The CRLF shebang went into the image as `#!/bin/sh\r`, so the
kernel looked for an interpreter literally named "/bin/sh\r" and every worker
container died with

    exec /worker-entrypoint.sh: no such file or directory

which reads as a missing file and is nothing of the sort. CI never saw it: a
Linux checkout has no autocrlf, so :latest was always fine.

Two assertions, because they fail in different places. The bytes check catches
the machine that actually builds :validation; the .gitattributes check is what
holds in CI, where the working tree is LF either way.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _tracked_shell_scripts():
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.split("\0") if p)


SCRIPTS = _tracked_shell_scripts()


def test_there_are_shell_scripts_to_check():
    """Guards against the glob silently matching nothing and vacuously passing."""
    assert "worker-entrypoint.sh" in SCRIPTS
    assert "entrypoint.sh" in SCRIPTS


@pytest.mark.parametrize("script", SCRIPTS)
def test_no_carriage_returns_in_the_working_tree(script):
    """This is the copy `docker build` reads."""
    assert b"\r" not in (ROOT / script).read_bytes(), (
        f"{script} has CRLF line endings; a container running it will fail with "
        f'"exec /{script}: no such file or directory"'
    )


@pytest.mark.parametrize("script", SCRIPTS)
def test_pinned_to_lf_in_gitattributes(script):
    """Without the pin, the next fresh clone on Windows reintroduces the CRLF."""
    eol = subprocess.run(
        ["git", "check-attr", "eol", "--", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert eol.endswith(": eol: lf"), f"{script} is not pinned to LF: {eol!r}"
