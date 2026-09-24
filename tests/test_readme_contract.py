"""The portfolio README contract: the first screen must not drift from the template.

The first screen is everything from ``# Name`` down to the end of "Try it in 60
seconds". String and regex checks only; this does not judge prose.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

AT_A_GLANCE_LABELS = (
    "**What it does**",
    "**Who it's for**",
    "**What stays on your device / what leaves it**",
    "**Runs on**",
    "**Not for**",
    "**Status**",
)


def _heading(title: str) -> int:
    index = README.find(f"\n{title}\n")
    assert index != -1, f"README has no {title!r} heading"
    return index


def test_should_open_with_the_title_then_the_package_description_as_tagline() -> None:
    lines = README.splitlines()
    assert re.fullmatch(r"# \S.*", lines[0])
    tagline = next(line for line in lines[1:] if line.strip() and not line.startswith("[!["))
    assert tagline == PROJECT["description"]
    assert len(PROJECT["description"]) <= 120


def test_should_show_at_most_four_badges_before_at_a_glance() -> None:
    assert README[: _heading("## At a glance")].count("[![") <= 4


@pytest.mark.parametrize("label", AT_A_GLANCE_LABELS)
def test_should_carry_every_at_a_glance_label_on_the_first_screen(label: str) -> None:
    assert label in README[: _heading("## How it works")]


def test_should_put_the_hero_caption_before_the_example_before_how_it_works() -> None:
    try_it = _heading("## Try it in 60 seconds")
    assert try_it < _heading("## How it works")
    caption = README.find("Real output of the example below")
    assert -1 < caption < try_it


def test_should_link_the_interactive_architecture_map_whose_source_exists() -> None:
    assert re.search(
        r"\[[^\]]*Explore the interactive architecture map[^\]]*\]"
        r"\(docs/architecture/index\.html\)",
        README,
    )
    assert (ROOT / "docs/architecture/runtime.architecture.json").is_file()


def test_should_state_beta_at_the_released_version_while_pre_1_0() -> None:
    # The release workflow tags v<pyproject version>, so this is the latest
    # pushed tag once a release is out.
    status = next(line for line in README.splitlines() if line.startswith("- **Status**"))
    version = str(PROJECT["version"])
    assert f"v{version}" in status
    if version.startswith("0."):
        assert "— Beta" in status


def test_should_resolve_every_relative_link_to_a_file_in_the_repo() -> None:
    targets = re.findall(r"\]\(([^)\s]+)\)", README)
    relative = [t for t in targets if not re.match(r"^(?:[a-z]+:|#)", t, flags=re.I)]
    assert relative, "the link extraction matched nothing; this check went blind"
    missing = [t for t in relative if not (ROOT / t.split("#")[0]).exists()]
    assert missing == []
