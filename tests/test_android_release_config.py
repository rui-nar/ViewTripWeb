"""Android release-build invariants (issue #136).

The Flutter template produces an Android config that compiles, installs and runs
in debug, and is broken in release: no INTERNET permission outside the debug
manifest, a `com.example.*` applicationId, and the debug key used for signing.
None of that shows up in `flutter test` or `flutter analyze` — the first symptom
is an installed app that cannot reach the API.

These assertions are on the config files themselves, because that is where the
mistakes live.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ANDROID = Path(__file__).resolve().parent.parent / "flutter_client" / "android"
MAIN_MANIFEST = ANDROID / "app" / "src" / "main" / "AndroidManifest.xml"
BUILD_GRADLE = ANDROID / "app" / "build.gradle.kts"

ANDROID_NS = "http://schemas.android.com/apk/res/android"
PACKAGE = "com.traxjourney.app"
# Every out-of-band link a user can receive. Each needs its own pathPrefix in
# the App Links filter, or that link type silently opens in a browser.
DEEP_LINK_PREFIXES = ("/share", "/join", "/verify-email")


def _attr(element, name):
    return element.get(f"{{{ANDROID_NS}}}{name}")


@pytest.fixture(scope="module")
def manifest():
    return ET.parse(MAIN_MANIFEST).getroot()


@pytest.fixture(scope="module")
def gradle():
    return BUILD_GRADLE.read_text(encoding="utf-8")


def test_internet_permission_is_in_the_main_manifest(manifest):
    """Declared in src/debug only, a release APK has no network access at all."""
    permissions = {_attr(node, "name") for node in manifest.findall("uses-permission")}
    assert "android.permission.INTERNET" in permissions


def test_location_permissions_survive(manifest):
    """The encounter picker defaults to the current position."""
    permissions = {_attr(node, "name") for node in manifest.findall("uses-permission")}
    assert "android.permission.ACCESS_FINE_LOCATION" in permissions
    assert "android.permission.ACCESS_COARSE_LOCATION" in permissions


def test_launcher_label_is_the_product_name(manifest):
    label = _attr(manifest.find("application"), "label")
    assert label == "TraxJourney"


def test_application_id_and_namespace_agree(gradle):
    """Both must be the published identity — it cannot change after release."""
    assert re.search(rf'applicationId\s*=\s*"{re.escape(PACKAGE)}"', gradle)
    assert re.search(rf'namespace\s*=\s*"{re.escape(PACKAGE)}"', gradle)
    assert "com.example" not in gradle


def test_main_activity_lives_in_the_namespace_package():
    """`.MainActivity` in the manifest resolves relative to the namespace."""
    activity = ANDROID / "app" / "src" / "main" / "kotlin" / Path(*PACKAGE.split(".")) / "MainActivity.kt"
    assert activity.is_file(), f"expected {activity}"
    kotlin_sources = list((ANDROID / "app" / "src" / "main" / "kotlin").rglob("MainActivity.kt"))
    assert kotlin_sources == [activity], f"stale activities: {kotlin_sources}"


def test_release_signing_prefers_a_real_keystore(gradle):
    """Debug signing is a documented local fallback, never the only option.

    A debug-signed APK on a release page cannot be upgraded by anyone who
    installed a properly signed one, and vice versa.
    """
    assert 'create("release")' in gradle
    assert "keystorePropertiesFile.exists()" in gradle
    assert 'signingConfigs.getByName("release")' in gradle
    # The template's unconditional assignment.
    assert not re.search(
        r'signingConfig\s*=\s*signingConfigs\.getByName\("debug"\)\s*\n\s*\}', gradle
    )


def test_no_template_todos_left(gradle):
    assert "TODO" not in gradle


def test_app_links_filter_covers_every_link_shape(manifest):
    activity = manifest.find("application/activity")
    verified = [
        node
        for node in activity.findall("intent-filter")
        if _attr(node, "autoVerify") == "true"
    ]
    assert verified, "no autoVerify intent-filter — links open in a browser"

    covered = set()
    for filter_node in verified:
        actions = {_attr(n, "name") for n in filter_node.findall("action")}
        categories = {_attr(n, "name") for n in filter_node.findall("category")}
        assert "android.intent.action.VIEW" in actions
        # BROWSABLE is what makes the filter match a link tapped in another app;
        # without it the filter is inert.
        assert "android.intent.category.BROWSABLE" in categories
        assert "android.intent.category.DEFAULT" in categories
        for data in filter_node.findall("data"):
            assert _attr(data, "scheme") == "https", "http links would not verify"
            assert _attr(data, "host") == "traxjourney.com"
            covered.add(_attr(data, "pathPrefix"))

    assert covered == set(DEEP_LINK_PREFIXES)


def test_deep_linking_is_enabled(manifest):
    """Without this the engine never hands the intent URL to go_router."""
    metadata = {
        _attr(node, "name"): _attr(node, "value")
        for node in manifest.findall("application/activity/meta-data")
    }
    assert metadata.get("flutter_deeplinking_enabled") == "true"


def test_release_has_no_cleartext_exemption():
    """The dev-server exemption must stay scoped to debug builds."""
    debug_config = (
        ANDROID / "app" / "src" / "debug" / "res" / "xml" / "network_security_config.xml"
    )
    assert debug_config.is_file()
    assert "networkSecurityConfig" not in MAIN_MANIFEST.read_text(encoding="utf-8")
