"""The Python version must be the same in production, CI and local dev.

The image the API actually runs on is pinned in the Dockerfile; CI pins its own
copy in the workflow. Nothing tied the two together, so they could drift apart
silently — and a third copy, whatever interpreter the developer's venv happens
to hold, drifts on its own the moment a new Python is installed on the machine.

A mismatch is invisible until it isn't: a 3.12+-only stdlib call passes locally
and on CI and then fails in the container, or the reverse. These assertions are
on the pin sites themselves, because that is where the mistakes live.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def _dockerfile_python() -> str:
    """The X.Y tag off the base image the API is built from."""
    match = re.search(r"^FROM python:(\d+\.\d+)", DOCKERFILE.read_text(encoding="utf-8"), re.M)
    assert match, "Dockerfile has no `FROM python:X.Y` line to read a version from"
    return match.group(1)


def _workflow_pythons() -> list[str]:
    """Every python-version the test workflow sets up, in file order."""
    workflow = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    return [
        str(step["with"]["python-version"])
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "python-version" in step.get("with", {})
    ]


def test_ci_pins_the_same_python_as_the_production_image():
    expected = _dockerfile_python()
    pinned = _workflow_pythons()
    assert pinned, "the test workflow no longer pins a Python version"
    assert set(pinned) == {expected}, (
        f"CI runs Python {sorted(set(pinned))} but the Dockerfile ships {expected}; "
        "tests would be proving something about an interpreter production never runs"
    )


def test_the_local_interpreter_matches_the_production_image():
    """Not a hard failure — a warning, so a stale venv is visible, not blocking."""
    expected = _dockerfile_python()
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running != expected:
        pytest.skip(
            f"this venv runs Python {running} but production ships {expected} — "
            "recreate the venv on the pinned version before trusting a local green run"
        )
