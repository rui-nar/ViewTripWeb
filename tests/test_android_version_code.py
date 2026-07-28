"""Tag -> Android versionCode mapping (issue #136).

Android decides whether an APK is an upgrade purely by versionCode. If the
mapping ever stops increasing with the version, users silently stop being able
to update, and the only fix is another release with a higher code.
"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "android_version_code",
    Path(__file__).resolve().parent.parent / "scripts" / "android_version_code.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
version_code = _module.version_code


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v0.47.0", 4700),
        ("v0.47.1", 4701),
        ("v0.48.0", 4800),
        ("v1.0.0", 10000),
        ("v1.2.3", 10203),
        ("0.47.0", 4700),  # the leading v is optional
        ("v0.47.0-rc1", 4700),  # suffixes are ignored
    ],
)
def test_known_tags(tag, expected):
    assert version_code(tag) == expected


def test_codes_increase_with_the_version():
    """Across a plausible release sequence, including the rollovers."""
    tags = [
        "v0.46.9",
        "v0.46.10",
        "v0.47.0",
        "v0.47.1",
        "v0.99.99",
        "v1.0.0",
        "v1.0.1",
        "v2.0.0",
    ]
    codes = [version_code(tag) for tag in tags]
    assert codes == sorted(codes)
    assert len(set(codes)) == len(codes)


def test_a_feature_bump_outranks_every_patch_of_the_previous_version():
    """The bump script's -Patch can run many times before the next feature bump."""
    assert version_code("v0.48.0") > version_code("v0.47.99")


@pytest.mark.parametrize("tag", ["latest", "v1.2", "", "vX.Y.Z", "1"])
def test_junk_tags_fail_loudly(tag):
    """A mistyped tag must break the build, not ship a wrong code."""
    with pytest.raises(ValueError):
        version_code(tag)


def test_component_overflow_is_rejected():
    """Beyond 99 the components would collide (0.100.0 and 1.0.0 both -> 10000)."""
    with pytest.raises(ValueError):
        version_code("v0.100.0")
    with pytest.raises(ValueError):
        version_code("v0.1.100")


def test_fits_in_the_android_limit():
    """Play and the platform cap versionCode at 2100000000."""
    assert version_code("v99.99.99") < 2_100_000_000
