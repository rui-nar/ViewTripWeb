#!/usr/bin/env python
"""Map a release tag to an Android versionCode.

Android identifies an upgrade solely by ``versionCode``: an APK whose code is
not strictly greater than the installed one cannot be installed over it. The
Flutter template takes the code from the ``+N`` build number in pubspec.yaml,
which this project never bumps (bump_version_and_release.ps1 only touches the
X.Y.Z part), so every release would ship code 1 and no user could ever update.

So derive it from the version instead:

    vX.Y.Z  ->  X * 10000 + Y * 100 + Z

0.47.0 -> 4700, 0.47.1 -> 4701, 0.48.0 -> 4800, 1.0.0 -> 10000. Monotonic for
any version this project's scheme can produce, and readable back to the tag at a
glance. The minor and patch components must stay under 100 for that to hold —
which the scheme guarantees, since a patch bump never reaches 100 before the
next feature release.

Used by .github/workflows/android-release.yml:

    flutter build apk --build-number=$(python scripts/android_version_code.py "$TAG")
"""

from __future__ import annotations

import re
import sys

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

# Ceiling for the minor and patch components, and the multiplier for the one
# above. Changing these renumbers every future release — never lower them.
COMPONENT_LIMIT = 100


def version_code(tag: str) -> int:
    """Return the Android versionCode for a ``vX.Y.Z`` tag.

    Raises ValueError on anything that is not a version tag, so a mistyped tag
    fails the build rather than silently shipping a wrong code.
    """
    match = _VERSION_RE.match(tag.strip())
    if not match:
        raise ValueError(f"not a version tag: {tag!r} (expected vX.Y.Z)")

    major, minor, patch = (int(part) for part in match.groups())
    if minor >= COMPONENT_LIMIT or patch >= COMPONENT_LIMIT:
        raise ValueError(
            f"minor/patch must stay below {COMPONENT_LIMIT} for codes to stay "
            f"ordered: {tag!r}"
        )
    return major * COMPONENT_LIMIT**2 + minor * COMPONENT_LIMIT + patch


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} vX.Y.Z", file=sys.stderr)
        return 2
    try:
        print(version_code(argv[1]))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
