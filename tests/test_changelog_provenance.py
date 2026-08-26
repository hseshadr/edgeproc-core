"""A released changelog section is immutable: `vX.Y.Z` must reproduce `X.Y.Z`.

This repository's whole thesis is provable provenance, so a rewritten release
record is precisely the failure it claims to prevent. The `[0.2.0]` section was
once edited in place *after* tagging — the header moved from `2026-07-14` to
`2026-07-20` and gained 23 lines describing post-tag work — which meant checking
out `v0.2.0` did not reproduce what `HEAD` called `0.2.0`.

This test compares every released (non-`Unreleased`) section at `HEAD` against
the same section as it stood at its own tag, and fails on any difference. New
work belongs under `[Unreleased]`; a shipped section is history.

Link-reference lines (`[0.2.0]: https://…/compare/…`) are excluded: that footer
is a growing index of every release, not part of any one release's record.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = "CHANGELOG.md"
GIT = shutil.which("git")

SECTION = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\][^\n]*\n(?:.*?)(?=^## \[|\Z)", re.M | re.S)
LINK_REFERENCE = re.compile(r"^\[[^\]]+\]:\s*\S+\s*$", re.M)


def _git(*args: str) -> str:
    """Run a read-only git command in the repo, raising on failure."""
    if GIT is None:  # pragma: no cover
        raise FileNotFoundError("git not on PATH")
    result = subprocess.run(  # noqa: S603
        [GIT, "-C", str(ROOT), *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def _released_sections(changelog: str) -> dict[str, str]:
    """Map version -> that version's section text, footer link lines removed."""
    sections: dict[str, str] = {}
    for match in SECTION.finditer(changelog):
        body = LINK_REFERENCE.sub("", match.group(0)).rstrip()
        sections[match.group("version")] = body
    return sections


def _release_tags() -> list[str]:
    """Every `vX.Y.Z` tag reachable in this clone."""
    found = _git("tag", "--list", "v*").split()
    return [tag for tag in found if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]


@pytest.fixture(scope="module")
def head_sections() -> dict[str, str]:
    """The released sections as they stand at `HEAD`."""
    return _released_sections((ROOT / CHANGELOG).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tags() -> list[str]:
    """Release tags; fail closed when provenance cannot be examined."""
    try:
        found = _release_tags()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:  # pragma: no cover
        pytest.fail(f"git unavailable, cannot verify changelog provenance: {exc}")
    if not found:  # pragma: no cover
        pytest.fail("no release tags in this clone — fetch tags to verify provenance")
    return found


def test_released_sections_are_unchanged_since_their_tag(
    tags: list[str], head_sections: dict[str, str]
) -> None:
    """No released section may differ from the way it shipped."""
    compared, drifted = 0, []
    for tag in tags:
        for version, body in _released_sections(_git("show", f"{tag}:{CHANGELOG}")).items():
            if version not in head_sections:
                drifted.append(f"{tag}: section [{version}] was deleted from HEAD")
                continue
            compared += 1
            if head_sections[version] != body:
                drifted.append(f"{tag}: section [{version}] was rewritten after tagging")

    assert drifted == []
    assert compared > 0, "vacuous pass: no released section was actually compared"


SHIPPED = "## [1.0.0] — 2020-01-01\n\n### Added\n- the thing that shipped\n"


@pytest.mark.parametrize(
    ("label", "rewritten"),
    [
        ("header date moved", "## [1.0.0] — 2099-12-31\n\n### Added\n- the thing that shipped\n"),
        ("body appended", f"{SHIPPED}- post-tag work smuggled in\n"),
        ("body reworded", "## [1.0.0] — 2020-01-01\n\n### Added\n- something else entirely\n"),
    ],
)
def test_the_comparison_would_notice_a_rewritten_section(label: str, rewritten: str) -> None:
    """Non-vacuity: the exact rewrites this test exists to catch must not compare equal."""
    assert _released_sections(SHIPPED)["1.0.0"] != _released_sections(rewritten)["1.0.0"], label


def test_footer_link_references_are_not_treated_as_release_content() -> None:
    """A new `[X.Y.Z]: …/compare/…` footer line must not read as a rewrite."""
    base = "## [1.0.0] — 2020-01-01\n\n### Added\n- a thing\n"
    with_footer = f"{base}\n[1.0.0]: https://example.invalid/compare/v0.9.0...v1.0.0\n"

    assert _released_sections(base) == _released_sections(with_footer)
