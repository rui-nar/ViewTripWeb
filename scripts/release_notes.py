#!/usr/bin/env python3
"""Generate user-facing release notes for a commit range.

The release script used to paste `git log --pretty=format:- %s` under a
"What's changed" heading. For v0.46.9 that produced five bullets for two real
changes: three were merge commits, and the two that mattered were written in
commit grammar (``fix(people): ...``) rather than anything a user would read.

This module turns the same range into grouped, linked, audience-separated
notes. Three layers, each degrading to the one below:

1. **Parsing** — drop merges and version bumps, read Conventional Commit
   prefixes, group by type, map the scope to a user-facing area.
2. **Trailers** — a ``Release-Note:`` trailer in the commit body wins over the
   subject line. No parser can turn "enforce the API quota process-wide" into a
   user benefit; only the author knows that, so this is where they write it.
3. **Highlights** (``--polish``) — asks Claude for a short intro paragraph.
   Entirely optional: no API key, no network, or any error means the notes are
   rendered without it.

Standalone use, to preview any range without cutting a release::

    python scripts/release_notes.py --from v0.46.9 --to HEAD
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Optional

REPO_URL = "https://github.com/rui-nar/ViewTripWeb"

# Scope → (area shown to the reader, audience). Audience splits "what changed in
# the app" from "what changed on the server", because one tag ships both the
# Flutter client and the FastAPI backend and the two have different readers.
# `internal` never reaches the reader's sections at all.
APP, SERVER, INTERNAL = "app", "server", "internal"

AREAS: dict[str, tuple[str, str]] = {
    "e2ee": ("Encryption", APP),
    "encryption": ("Encryption", APP),
    "encounters": ("People & encounters", APP),
    "people": ("People & encounters", APP),
    "groups": ("People & encounters", APP),
    "poster": ("Posters", APP),
    "photos": ("Photos", APP),
    "immich": ("Immich", APP),
    "admin": ("Admin dashboard", APP),
    "editor": ("Track editor", APP),
    "track-edit": ("Track editor", APP),
    "track-save": ("Track editor", APP),
    "activity-edit": ("Track editor", APP),
    "activity-editor": ("Track editor", APP),
    "activity-split": ("Track editor", APP),
    "split": ("Track editor", APP),
    "activity-panel": ("Activity panel", APP),
    "strava": ("Strava", APP),
    "polarsteps": ("Polarsteps", APP),
    "gpx": ("GPX import", APP),
    "map": ("Map", APP),
    "geo": ("Map", APP),
    "view": ("Map", APP),
    "view-mode": ("Map", APP),
    "counters": ("Trip stats", APP),
    "stats": ("Trip stats", APP),
    "memory": ("Memories", APP),
    "memories": ("Memories", APP),
    "journal": ("Journal", APP),
    "translations": ("Translations", APP),
    "day-editor": ("Day editor", APP),
    "segment-dialog": ("Segments", APP),
    "segments": ("Segments", APP),
    "share": ("Sharing", APP),
    "social": ("Sharing", APP),
    "auth": ("Sign-in", APP),
    "companion": ("Companions", APP),
    "members": ("Companions", APP),
    "invites": ("Companions", APP),
    "projects": ("Trips", APP),
    "project_io": ("Trips", APP),
    "project-notifier": ("Trips", APP),
    "manage": ("Trips", APP),
    "splash": ("Splash screen", APP),
    "web": ("Web app", APP),
    "client": ("Web app", APP),
    "android": ("Android app", APP),
    "api": ("API", SERVER),
    "db": ("Database", SERVER),
    "alembic": ("Database", SERVER),
    "backup": ("Backups", SERVER),
    "email": ("Email", SERVER),
    "metrics": ("Monitoring", SERVER),
    "logging": ("Logging", SERVER),
    "release": ("Release tooling", INTERNAL),
    "ci": ("CI", INTERNAL),
    "deps": ("Dependencies", INTERNAL),
    "docker": ("Packaging", INTERNAL),
    "deploy": ("Deployment", INTERNAL),
    "test": ("Tests", INTERNAL),
    "tests": ("Tests", INTERNAL),
}

# Conventional Commit types that reach the reader, and the section each lands in.
SECTIONS = {"feat": "New", "fix": "Fixed", "perf": "Fixed"}

_COMMIT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<subject>.+)$"
)
_ISSUE_RE = re.compile(r"#(\d+)")
# A trailing "(#123)" / "(#125, #133)" group — the convention for tagging a
# subject with its issue and PR. Only these are stripped and turned into links;
# a reference woven into the sentence ("issue #45 follow-up") is prose and stays
# put, and GitHub auto-links it in a release body anyway.
_TRAILING_REFS_RE = re.compile(r"\s*\(\s*#\d+(?:[,\s]+#\d+)*\s*\)\s*$")
_TRAILER_RE = re.compile(r"^(Release-Note|Upgrade-Note):\s*(.+)$", re.IGNORECASE)

# Commits that are pure bookkeeping — never interesting, in any section.
_SKIP_SUBJECTS = (
    re.compile(r"^chore: bump version", re.IGNORECASE),
    re.compile(r"^Merge ", re.IGNORECASE),
)

_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"


@dataclass(frozen=True)
class Change:
    """One user-visible change, ready to render."""

    kind: str
    area: str
    audience: str
    subject: str
    release_note: Optional[str]
    upgrade_note: Optional[str]
    refs: tuple[str, ...]

    @property
    def section(self) -> str:
        return SECTIONS.get(self.kind, "Internal")

    @property
    def text(self) -> str:
        """What the reader sees — the author's line if they wrote one."""
        return self.release_note or self.subject


# ── Parsing ───────────────────────────────────────────────────────────────────


def _trailers(body: str) -> dict[str, str]:
    """Read ``Release-Note:`` / ``Upgrade-Note:`` trailers from a commit body.

    A trailer runs until a blank line, so it can wrap across lines the way the
    rest of the commit body does.
    """
    found: dict[str, str] = {}
    key: Optional[str] = None
    for line in body.splitlines():
        match = _TRAILER_RE.match(line.strip())
        if match:
            key = match.group(1).lower()
            found[key] = match.group(2).strip()
        elif key and line.strip():
            found[key] = f"{found[key]} {line.strip()}"
        else:
            key = None
    return found


def _classify(scope: Optional[str], files: Iterable[str]) -> tuple[str, str]:
    """Resolve (area, audience) from the scope, falling back to changed paths.

    The scope table is the accurate source when it has an entry. When it
    doesn't, which tree the commit touched is the next best signal — anything
    under flutter_client/ is something a user can see.
    """
    if scope:
        # `fix(map,stats)` — take the first, that's the primary area.
        primary = scope.split(",")[0].strip().lower()
        if primary in AREAS:
            return AREAS[primary]

    # No scope means no area label — under an "In the app" heading, a generic
    # "**App** —" prefix on every bullet is noise.
    label = scope.split(",")[0].strip().title() if scope else ""
    paths = list(files)
    if any(p.startswith("flutter_client/") for p in paths):
        return label, APP
    if paths:
        return label, SERVER
    return label, INTERNAL


def parse_commits(raw: str) -> list[Change]:
    """Turn ``git log`` output (see :func:`git_log`) into changes, newest last.

    Merge commits and version bumps are dropped: they duplicate or bury the
    real change, which is what made the old flat list unreadable.
    """
    changes: list[Change] = []
    for record in raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        subject, body, files_blob = (record.split(_FIELD_SEP) + ["", ""])[:3]
        subject = subject.strip()
        if not subject or any(p.match(subject) for p in _SKIP_SUBJECTS):
            continue

        match = _COMMIT_RE.match(subject)
        kind = match.group("type") if match else "other"
        scope = match.group("scope") if match else None
        text = match.group("subject").strip() if match else subject

        trailers = _trailers(body)
        area, audience = _classify(scope, (f for f in files_blob.split("\n") if f))
        if match and match.group("breaking"):
            trailers.setdefault("upgrade-note", text)

        refs: list[str] = []
        while (trailing := _TRAILING_REFS_RE.search(text)) is not None:
            refs = _ISSUE_RE.findall(trailing.group(0)) + refs
            text = text[: trailing.start()]

        changes.append(
            Change(
                kind=kind,
                area=area,
                audience=audience,
                subject=text.strip(),
                release_note=trailers.get("release-note"),
                upgrade_note=trailers.get("upgrade-note"),
                refs=tuple(dict.fromkeys(refs)),
            )
        )
    return list(reversed(changes))


# ── Rendering ─────────────────────────────────────────────────────────────────


def _bullet(change: Change, repo_url: str) -> str:
    # One parenthesised group, however many refs: a squash commit carries both
    # its issue and its PR number, and "(#125) (#133)" reads like two changes.
    # /issues/N redirects to /pull/N when N is a PR, so one URL shape covers both.
    links = ", ".join(f"[#{n}]({repo_url}/issues/{n})" for n in change.refs)
    text = change.text.rstrip(".")
    if change.area:
        prefix = f"**{change.area}** — "
    else:
        # Nothing in front of it, so the subject starts the sentence — commit
        # subjects are lowercase by convention.
        prefix = ""
        text = text[:1].upper() + text[1:]
    return f"- {prefix}{text}." + (f" ({links})" if links else "")


def _section(changes: list[Change], repo_url: str) -> list[str]:
    """Render one section, splitting by audience only when both are present.

    A lone "In the app" heading over an all-app section is noise, so the
    sub-headings appear only when they're actually telling the reader apart.
    """
    app = [c for c in changes if c.audience == APP]
    server = [c for c in changes if c.audience == SERVER]
    lines: list[str] = []
    if app and server:
        lines.append("### In the app\n")
        lines += [_bullet(c, repo_url) for c in app]
        lines.append("\n### Server & deployment\n")
        lines += [_bullet(c, repo_url) for c in server]
    else:
        lines += [_bullet(c, repo_url) for c in app + server]
    return lines


def render(
    changes: list[Change],
    *,
    version: str,
    previous: str,
    repo_url: str = REPO_URL,
    highlights: Optional[str] = None,
) -> str:
    """Render the full release body as GitHub-flavoured markdown."""
    visible = [c for c in changes if c.audience != INTERNAL and c.section != "Internal"]
    internal = [c for c in changes if c not in visible]

    out: list[str] = [f"# ViewTripWeb {version}", ""]
    count = len(visible)
    noun = "change" if count == 1 else "changes"
    out += [f"_{count} {noun} since {previous}_", ""]

    if highlights:
        out += ["## ✨ Highlights", "", highlights.strip(), ""]

    for title, emoji in (("New", "🚀"), ("Fixed", "🐛")):
        section = [c for c in visible if c.section == title]
        if section:
            out += [f"## {emoji} {title}", ""]
            out += _section(section, repo_url)
            out.append("")

    upgrades = [c for c in changes if c.upgrade_note]
    if upgrades:
        out += ["## ⚠️ Upgrade notes", ""]
        out += [f"- **{c.area}** — {c.upgrade_note.rstrip('.')}." for c in upgrades]
        out.append("")

    if internal:
        out += [
            f"<details><summary>Internal changes ({len(internal)})</summary>",
            "",
        ]
        out += [f"- {c.subject}" for c in internal]
        out += ["", "</details>", ""]

    if not visible and not internal:
        out += [f"_No changes since {previous}._", ""]

    out.append(f"**Full changelog**: [`{previous}...{version}`]"
               f"({repo_url}/compare/{previous}...{version})")
    return "\n".join(out) + "\n"


# ── Git plumbing ──────────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    """Run git and decode as UTF-8.

    Explicit encoding, not the platform default: this repo's commit messages
    are full of em-dashes and accented characters, and on Windows the default
    cp1252 decode raises UnicodeDecodeError on them.
    """
    return subprocess.run(
        ["git", *args], capture_output=True, check=True,
        encoding="utf-8", errors="replace",
    ).stdout


def previous_tag(ref: str = "HEAD") -> Optional[str]:
    """The most recent tag reachable from *ref*.

    Asked of git rather than derived from pubspec.yaml: a tag cut by hand, or a
    pubspec that drifted, would otherwise silently produce the wrong range.
    """
    try:
        return _git("describe", "--tags", "--abbrev=0", ref).strip() or None
    except subprocess.CalledProcessError:
        return None


def git_log(from_ref: Optional[str], to_ref: str = "HEAD") -> str:
    """Commits in the range, with subject, body and changed paths per record."""
    spec = f"{from_ref}..{to_ref}" if from_ref else to_ref
    # The record separator leads each entry, not trails it: --name-only appends
    # the changed paths *after* the pretty format, so a trailing separator would
    # push every commit's file list into the next record.
    return _git(
        "log", spec, "--no-merges", "--name-only",
        f"--pretty=format:{_RECORD_SEP}%s{_FIELD_SEP}%b{_FIELD_SEP}",
    )


# ── Optional: LLM highlights ──────────────────────────────────────────────────

_HIGHLIGHTS_PROMPT = """\
Write the "Highlights" paragraph for a release of ViewTrip, an app for mapping \
and sharing multi-week trips (Flutter client, FastAPI server).

Below are the changes in this release, already grouped. Write 2-3 sentences for \
someone who uses the app, in plain language: what is now possible or fixed, and \
why it matters. Lead with whatever is most significant.

Do not use a heading, a bullet list, issue numbers, or the words "this release". \
Do not invent anything that is not in the list. If the changes are all minor, \
say so briefly rather than inflating them.

Changes:
{changes}
"""


def polish(changes: list[Change], *, model: str = "claude-opus-5") -> Optional[str]:
    """Ask Claude for a short highlights paragraph; None if unavailable.

    Every failure path returns None so the caller renders the deterministic
    notes instead. A release must never be blocked by a missing API key, an
    offline machine, or a bad day at the API — the highlights are a garnish,
    not the notes.
    """
    visible = [c for c in changes if c.audience != INTERNAL and c.section != "Internal"]
    if not visible:
        return None

    try:
        import anthropic
    except ImportError:
        print("note: `pip install anthropic` to enable --polish", file=sys.stderr)
        return None

    listing = "\n".join(f"- [{c.section}] {c.area}: {c.text}" for c in visible)
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user",
                       "content": _HIGHLIGHTS_PROMPT.format(changes=listing)}],
        )
    except Exception as exc:  # noqa: BLE001 — never fail a release over a garnish
        print(f"note: highlights unavailable ({exc.__class__.__name__}); "
              f"continuing without them", file=sys.stderr)
        return None

    if response.stop_reason == "refusal":
        print("note: highlights declined by the model; continuing without them",
              file=sys.stderr)
        return None

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="from_ref", default=None,
                        help="start ref (default: the most recent tag)")
    parser.add_argument("--to", dest="to_ref", default="HEAD", help="end ref")
    parser.add_argument("--version", default=None,
                        help="version being released (default: the --to ref)")
    parser.add_argument("--repo-url", default=REPO_URL)
    parser.add_argument("--polish", action="store_true",
                        help="add an LLM-written highlights paragraph")
    parser.add_argument("--model", default="claude-opus-5")
    args = parser.parse_args(argv)

    from_ref = args.from_ref or previous_tag(args.to_ref)
    changes = parse_commits(git_log(from_ref, args.to_ref))
    highlights = polish(changes, model=args.model) if args.polish else None

    body = render(
        changes,
        version=args.version or args.to_ref,
        previous=from_ref or "the beginning",
        repo_url=args.repo_url,
        highlights=highlights,
    )
    # Written as UTF-8 bytes rather than through sys.stdout: the section
    # headings carry emoji, and a Windows console defaults to cp1252, which
    # raises UnicodeEncodeError on them.
    sys.stdout.buffer.write(body.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
