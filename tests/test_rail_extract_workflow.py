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
import json
import os
import shutil
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


def test_the_plan_job_runs_with_only_what_it_installs(tmp_path):
    """The matrix command must work in the plan job's environment, which is
    PyYAML and nothing else.

    It did not. `osmium` and `requests` were imported at module scope, so the
    step that prints the matrix died with ModuleNotFoundError before printing
    anything — the plan job failed on every scheduled run and `build` never
    started. Nothing caught it, because every test here imports the module in a
    developer's environment where both are installed and asserts on the text of
    the workflow file rather than on the command working.

    So: run it for real, with the heavy pair made unimportable. PYTHONPATH takes
    precedence over site-packages, so a stub module that raises stands in for
    "not installed" without touching the environment the suite runs in.
    """
    for module in ("osmium", "requests"):
        (tmp_path / f"{module}.py").write_text(
            f'raise ImportError("No module named {module!r}")\n', encoding="utf-8"
        )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, "scripts/build_rail_extract.py", "regions", "--json"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == rail.load_regions()


# ---------------------------------------------------------------------------
# Nothing raw leaves the runner
# ---------------------------------------------------------------------------

def test_the_raw_extract_is_downloaded_outside_the_checkout(jobs):
    """A work dir inside the workspace would put a 4.83 GB file where
    upload-artifact, docker build and git all look.

    Only the workflow can say where the runner puts it, so this one is on the
    file. That the script then *deletes* it is asserted on the script's own
    behaviour, in test_rail_extract.py.
    """
    build = _steps_text(jobs["build"])
    assert "--work-dir \"$RUNNER_TEMP" in build
    assert "--out-dir dist/rail" in build


def test_only_filtered_artifacts_are_uploaded(jobs):
    """The release gets the ~10 MB result and the manifest, and nothing else."""
    upload = [step for step in jobs["build"]["steps"]
              if step.get("uses", "").startswith("actions/upload-artifact")]
    assert [step["with"]["path"] for step in upload] == ["dist/rail/"]

    publish = _steps_text(jobs["publish"])
    assert "dist/rail/*-rail.osm.pbf" in publish
    assert "dist/rail/manifest.json" in publish


def test_no_raw_extract_is_tracked_in_the_repo():
    """The image is built with `COPY . .`, so tracked is shipped. A raw country
    extract is 0.5-4.8 GB; every fixture the suite needs is a filtered cut of
    one and fits in a few hundred KB."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.pbf", "*.osm.bz2", "*.osm"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    paths = sorted(p for p in tracked.split("\0") if p)
    assert paths, "the fixtures are gone, not the guard"
    for path in paths:
        assert path.startswith("tests/fixtures/"), f"{path} is not a fixture"
        assert (ROOT / path).stat().st_size < 1_000_000, f"{path} is not filtered"


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
    assert publish.index("build_rail_extract.py manifest") < \
        publish.index("gh release upload")


def test_the_publish_job_checks_coverage_against_the_planned_matrix(jobs, workflow):
    """The script refuses an incomplete manifest (test_rail_extract.py); this is
    the wiring that makes the publish job actually ask it to.

    Both arguments matter and neither is decoration: without `--base` a
    one-region dispatch republishes a manifest that disowns the other 48, and
    without `--expect` a batch of transient Geofabrik failures publishes a
    partial manifest as the current release. `force_publish` is the way past it
    on purpose rather than by accident.
    """
    manifest_step = _steps_text(jobs["publish"])
    assert "--base released/manifest.json" in manifest_step
    assert "--expect \"$EXPECTED\"" in manifest_step
    assert jobs["publish"]["needs"] == ["plan", "build"], \
        "the expected coverage is the plan job's matrix"
    assert "force_publish" in workflow[True]["workflow_dispatch"]["inputs"]
    assert "--force" in manifest_step


def test_a_subset_rebuild_updates_the_release_it_patches(jobs):
    """A dispatch of one region must not open a new dated release: the other 48
    regions exist only as the previous release's assets, so a new tag would hold
    Denmark alone and "latest rail-data-*" would resolve to it."""
    publish = _steps_text(jobs["publish"])
    assert "gh release list" in publish
    assert "startswith(\"rail-data-\")" in publish


def test_only_the_publish_job_can_write(workflow, jobs):
    assert workflow["permissions"]["contents"] == "read"
    assert jobs["publish"]["permissions"]["contents"] == "write"
    assert "permissions" not in jobs["build"]


# ---------------------------------------------------------------------------
# A subset rebuild must never publish a manifest holding only what it built
# ---------------------------------------------------------------------------

def _working_bash() -> str | None:
    """A POSIX shell that actually runs.

    `shutil.which("bash")` is not enough on Windows: WSL installs a `bash` shim
    that fails with `execvpe(/bin/bash) failed` when no distribution is
    installed, which would have let this test "pass" on the wrong exit code.
    """
    for candidate in ("bash", "C:/Program Files/Git/bin/bash.exe"):
        if shutil.which(candidate) is None and not Path(candidate).exists():
            continue
        try:
            if subprocess.run([candidate, "-c", "exit 7"],
                              capture_output=True).returncode == 7:
                return candidate
        except OSError:
            continue
    return None


BASH = _working_bash()


def _step(job: dict, name: str) -> dict:
    for step in job["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r}")


@pytest.mark.skipif(BASH is None, reason="needs a working POSIX shell")
@pytest.mark.parametrize(
    "requested, release_exists, expected_exit",
    [
        ("europe/denmark", True, 1),
        ("europe/denmark", False, 0),
        ("", True, 0),
    ],
    ids=["subset of an existing release refuses",
         "subset with no release yet bootstraps",
         "full run proceeds"],
)
def test_a_subset_rebuild_stops_only_when_it_would_disown_regions(
    jobs, tmp_path, requested, release_exists, expected_exit
):
    """The merge that fixes the one-region-manifest bug fails *open*.

    `--base` ignores a file that is not there, which is right for the genuine
    first run and wrong for a subset patch: a transient `gh` error, a
    rate-limited token or a release whose manifest asset is missing leaves the
    merge with nothing to merge into, and the run then clobbers a 49-region
    manifest with the one region it built — on a release that still holds all
    49 .pbf assets. `--expect` cannot catch it, because on a dispatch it *is*
    the subset that was requested.

    But refusing on a *missing base* alone also refused the bootstrap, which
    the first real run of this pipeline hit: dispatching one country when no
    `rail-data-*` release exists is not clobbering anything, it is seeding
    coverage a country at a time. So the guard turns on whether there is a
    release to disown regions from, and these three cases are the whole of it.

    Run for real against a fake `gh`, because this is shell inside YAML and
    asserting on its text is how the bug it fixes got shipped.
    """
    script = _step(jobs["publish"], "Fetch the manifest being updated")["run"]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # `release view` decides whether the release exists; `release download`
    # always fails, which is the "base could not be fetched" half.
    verdict = 0 if release_exists else 1
    (fake_bin / "gh").write_text(
        chr(10).join([
            "#!/bin/sh",
            f'if [ "$1 $2" = "release view" ]; then exit {verdict}; fi',
            "exit 1",
            "",
        ]),
        encoding="utf-8",
    )
    (fake_bin / "gh").chmod(0o755)

    result = subprocess.run(
        [BASH, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
             "TAG": "rail-data-2026-08-02", "REQUESTED": requested},
        capture_output=True, text=True,
    )

    assert result.returncode == expected_exit, result.stdout + result.stderr
