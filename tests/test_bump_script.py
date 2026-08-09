"""Release-script invariants.

The bump script derives the release-notes range from `git describe`. Unmatched,
that returns the nearest tag of *any* kind — so the non-release `validation` tag
(issue #191) became the range base and silently truncated a release's notes to
the commits since the last validation build. Nothing fails; the notes are just
quietly incomplete, which is only noticeable by reading them.

The assertion is on the script text, because that is where the mistake lives.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bump_version_and_release.ps1"


def test_previous_tag_lookup_matches_only_release_tags():
    """`git describe` must ignore non-release tags such as `validation`."""
    code = [
        line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    describes = [
        match.group(0)
        for line in code
        for match in [re.search(r"git describe[^\r\n)]*", line)]
        if match
    ]

    assert describes, "expected the script to derive the previous tag from git describe"
    for call in describes:
        assert "--match" in call, f"git describe without --match picks up any tag: {call}"
        assert re.search(r'--match\s+"v\[0-9\]\*"', call), (
            f"--match must be restricted to vN* release tags: {call}"
        )
