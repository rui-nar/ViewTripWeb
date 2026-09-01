"""deploy.ps1 invariants for the -TagOnly path.

-TagOnly hands the :validation build to GitHub Actions by force-pushing the
floating `validation` tag. Two things make it dangerous if they ever drift:
it must tag the freshly fetched `origin/main` (a local `main` may be behind, or
carry unpushed commits, and would publish an image nobody else can reproduce),
and it must stop before the build/deploy steps, since a force-push that then
went on to build and deploy locally is not what the flag promises.

The assertions are on the script text, because that is where such a mistake
would live, and no test host has the GHCR/VPS credentials to run it.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy.ps1"

# deploy.ps1 is gitignored (it carries host/key details), so it exists only on a
# maintainer's machine — unlike bump_version_and_release.ps1, which is tracked.
# Skip rather than fail on CI and in fresh clones.
if not SCRIPT.exists():
    pytest.skip("deploy.ps1 not present (gitignored, local-only)", allow_module_level=True)

TEXT = SCRIPT.read_text(encoding="utf-8-sig")
LINES = TEXT.splitlines()


def _code_lines():
    """Script lines with comments and the comment-based help block dropped."""
    out, in_help = [], False
    for line in LINES:
        stripped = line.strip()
        if stripped.startswith("<#"):
            in_help = True
        if in_help:
            if stripped.endswith("#>"):
                in_help = False
            continue
        if stripped.startswith("#"):
            continue
        out.append(line)
    return out


def _index_of(pattern):
    """Index of the first code line matching `pattern`, or -1."""
    for i, line in enumerate(_code_lines()):
        if re.search(pattern, line):
            return i
    return -1


def test_tag_only_is_declared_as_a_switch():
    assert re.search(r"^\s*\[switch\]\$TagOnly,?\s*$", TEXT, re.MULTILINE), (
        "expected a [switch]$TagOnly parameter in the param block"
    )


def test_tag_only_is_rejected_outside_validation():
    """The user asked for a flag that is only valid with -Target Validation."""
    guard = _index_of(r"if \(\$TagOnly -and \$Target -ne 'Validation'\)")
    assert guard != -1, "expected -TagOnly to be rejected unless -Target is Validation"

    action = _index_of(r"git tag -f validation")
    assert action != -1, "expected -TagOnly to move the validation tag"
    assert guard < action, "the -Target guard must run before the tag is moved"


def test_tag_only_runs_the_two_documented_git_commands():
    """The flag is exactly the manual flow: tag origin/main, force-push the tag."""
    code = "\n".join(_code_lines())

    fetch = _index_of(r"git fetch origin")
    tag = _index_of(r"^\s*git tag -f validation origin/main\b")
    assert tag != -1, "expected `git tag -f validation origin/main`"
    assert fetch != -1 and fetch < tag, (
        "origin/main is only as fresh as the last fetch — fetch before tagging it"
    )

    push = _index_of(r"^\s*git push origin validation --force\b")
    assert push != -1, "expected `git push origin validation --force`"
    assert tag < push, "the tag must be moved before it is pushed"

    assert not re.search(r"git (tag|push)[^\n]*--delete", code), (
        "-TagOnly must only move the tag, never delete it"
    )


def test_tag_only_stops_before_building_or_deploying():
    code = _code_lines()
    block = _index_of(r"^if \(\$TagOnly\)")
    assert block != -1, "expected a top-level `if ($TagOnly)` block"

    exits = [i for i, line in enumerate(code) if re.search(r"^\s+exit 0\s*$", line)]
    assert exits, "expected -TagOnly to exit after pushing the tag"
    stop = exits[0]
    assert stop > block

    for pattern, what in (
        (r"flutter build web", "the Flutter build"),
        (r"docker build ", "the Docker build"),
        (r"docker push ", "the image push"),
        (r"\| ssh ", "the remote deployment"),
    ):
        step = _index_of(pattern)
        assert step != -1, f"{what} disappeared from the script"
        assert stop < step, f"-TagOnly must exit before {what}"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_script_parses():
    """A syntax error here is only discovered at deploy time otherwise."""
    check = (
        "$errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', "
        "[ref]$null, [ref]$errors) > $null; "
        "if ($errors) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", check],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"deploy.ps1 does not parse:\n{result.stdout}{result.stderr}"
