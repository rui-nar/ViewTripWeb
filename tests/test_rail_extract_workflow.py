"""Where the rail extracts are built, and what must never leave the runner (#345).

The raw Europe extract is 34.9 GB and the VPS has 40 GB in total, prod and val
included. So the whole pipeline rests on one invariant — **the raw file exists
only on a throwaway CI runner** — and that invariant lives in a workflow file
and two ignore files, where nothing else would ever check it. A single
``COPY . .`` in the Dockerfile is all it takes for a stray extract in the
working tree to become part of an image.

The other half is coverage. Phase 0 decided that adding a country is a config
change plus a rebuild, never a code change, so the matrix has to be read from
``config/rail_regions.yml`` at run time rather than listed in the workflow.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "rail-extract.yml"
FIXTURE = ROOT / "tests" / "fixtures" / "rail_mannheim.osm.pbf"

_spec = importlib.util.spec_from_file_location(
    "build_rail_extract_workflow", ROOT / "scripts" / "build_rail_extract.py"
)
rail = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rail
_spec.loader.exec_module(rail)

# Aggregates Geofabrik also publishes under europe/. Each one duplicates
# countries the config already lists, which would double the build and leave
# phase 3 with two regions claiming the same coordinate.
AGGREGATE_REGIONS = {
    "europe/alps", "europe/dach", "europe/britain-and-ireland",
    "europe/united-kingdom",
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def jobs(workflow) -> dict:
    return workflow["jobs"]


def _steps_text(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


# ---------------------------------------------------------------------------
# Coverage is configuration
# ---------------------------------------------------------------------------

def test_regions_are_geofabrik_paths():
    regions = rail.load_regions()
    assert regions
    assert all(region.startswith("europe/") for region in regions)
    # The two the filter was measured against in the spike (issue #345).
    assert {"europe/denmark", "europe/germany"} <= set(regions)


def test_no_aggregate_regions():
    assert not AGGREGATE_REGIONS & set(rail.load_regions())


def test_colliding_file_names_are_rejected(tmp_path):
    """The artifact is named after the last path component, so two regions
    sharing one would have the second overwrite the first in the release."""
    config = tmp_path / "regions.yml"
    config.write_text("regions: [europe/georgia, asia/georgia]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="collide"):
        rail.load_regions(config)


def test_an_empty_config_is_rejected(tmp_path):
    config = tmp_path / "regions.yml"
    config.write_text("regions: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no regions"):
        rail.load_regions(config)


def test_the_matrix_is_read_from_the_config_not_the_workflow(jobs):
    """Adding a country must not require editing the workflow."""
    matrix = jobs["build"]["strategy"]["matrix"]["region"]
    assert "needs.plan.outputs.regions" in matrix
    assert "build_rail_extract.py regions --json" in _steps_text(jobs["plan"])


# ---------------------------------------------------------------------------
# Nothing raw leaves the runner
# ---------------------------------------------------------------------------

def test_the_raw_extract_is_downloaded_outside_the_checkout(jobs):
    """A work dir inside the workspace would put a 4.83 GB file where
    upload-artifact, docker build and git all look."""
    build = _steps_text(jobs["build"])
    assert "--work-dir \"$RUNNER_TEMP" in build
    assert "--out-dir dist/rail" in build


def test_the_build_job_refuses_to_publish_anything_oversized(jobs):
    """A tripwire on the script's own cleanup, in the job that would upload."""
    build = _steps_text(jobs["build"])
    assert "find dist/rail -size +100M" in build
    assert "-name '*-source.osm.pbf'" in build


def test_only_filtered_artifacts_are_uploaded(jobs):
    """The release gets the ~10 MB result and the manifest, and nothing else."""
    upload = [step for step in jobs["build"]["steps"]
              if step.get("uses", "").startswith("actions/upload-artifact")]
    assert [step["with"]["path"] for step in upload] == ["dist/rail/"]

    publish = _steps_text(jobs["publish"])
    assert "dist/rail/*-rail.osm.pbf dist/rail/manifest.json" in publish


def test_no_raw_extract_is_tracked_in_the_repo():
    """The image is built with `COPY . .`, so tracked is shipped."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.pbf", "*.osm.bz2", "*.osm"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    paths = sorted(p for p in tracked.split("\0") if p)
    assert paths == ["tests/fixtures/rail_mannheim.osm.pbf"]


def test_the_fixture_stays_small():
    """It is a test input, not a data set; keep it reviewable in a diff."""
    assert FIXTURE.stat().st_size < 1_000_000


def test_extracts_are_gitignored_except_the_fixture():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.osm.pbf" in ignore
    assert "!tests/fixtures/*.osm.pbf" in ignore


def test_extracts_cannot_reach_an_image():
    """Belt and braces with .gitignore: an untracked extract in the working
    tree is still in `docker build`'s context."""
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*.osm.pbf" in ignore
    assert "dist/" in ignore


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_the_build_is_scheduled_and_manually_triggerable(workflow):
    """Monthly is ample — rail alignments change over years — but a region that
    fails has to be re-runnable on the spot."""
    # PyYAML reads the unquoted key `on:` as the boolean True.
    triggers = workflow[True]
    assert triggers["schedule"], "no schedule: the extracts would never refresh"
    assert "workflow_dispatch" in triggers
    assert "regions" in triggers["workflow_dispatch"]["inputs"]


def test_one_build_at_a_time(workflow):
    """Two runs would race on the same release tag."""
    assert workflow["concurrency"]["group"] == "rail-extract"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_the_manifest_is_verified_before_it_is_published(jobs):
    """The artifacts cross a job boundary; a truncated one must fail here."""
    publish = _steps_text(jobs["publish"])
    assert publish.index("build_rail_extract.py manifest") < publish.index("gh release")


def test_only_the_publish_job_can_write(workflow, jobs):
    assert workflow["permissions"]["contents"] == "read"
    assert jobs["publish"]["permissions"]["contents"] == "write"
    assert "permissions" not in jobs["build"]
