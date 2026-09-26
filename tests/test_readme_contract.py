"""The README contract: plain English, in a fixed order, with no internal jargon.

The README follows the plain-English standard the owner approved on
hseshadr/aml-filter#151: a one-sentence description, the fastest way to try it,
the problem in a short paragraph, a technical-docs line, then Try it, How it
works, honest limits, Install, Develop, More detail and License, in that order.
Deep technical material lives in docs/ARCHITECTURE.md. String and regex checks
only; this does not judge prose.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

SECTION_ORDER = (
    "## Try it",
    "## How it works",
    "## What it does not do",
    "## When to use something else",
    "## Install",
    "## Develop",
    "## More detail",
    "## License",
)

#: Words that made the old README read like "AI English" to its owner, plus the
#: retired portfolio template headings. Matched case-insensitively as whole words.
BANNED = (
    "northstar",
    "seam",
    "lego",
    "trust envelope",
    "receipt",
    "fail-closed",
    "gate",
    "fleet",
    "portfolio",
    "production-ready",
    "robust",
    "blazing",
    "enterprise-grade",
    "seamless",
    "at a glance",
    "try it in 60 seconds",
    "below the fold",
)

#: Docs a new reader must be able to reach from the technical-docs line.
TECHNICAL_DOCS = ("docs/ARCHITECTURE.md", "docs/GETTING_STARTED.md")


def _prose(text: str) -> str:
    """The text a reader reads as words: fenced blocks and inline code removed.

    Commands keep their real names (the check task is literally ``poe gate``);
    the ban is on vocabulary in sentences.
    """
    without_fences = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", without_fences)


def _heading(title: str) -> int:
    index = README.find(f"\n{title}\n")
    assert index != -1, f"README has no {title!r} heading"
    return index


def _section(title: str) -> str:
    start = _heading(title)
    following = [_heading(t) for t in SECTION_ORDER if _heading(t) > start]
    return README[start : min(following, default=len(README))]


def test_should_open_with_the_title_then_the_package_description() -> None:
    lines = README.splitlines()
    assert lines[0] == "# edgeproc-core"
    tagline = next(line for line in lines[1:] if line.strip() and not line.startswith("[!["))
    assert tagline == PROJECT["description"]
    assert len(PROJECT["description"]) <= 120


def test_should_put_the_one_line_install_in_bold_right_under_the_description() -> None:
    lines = [line for line in README.splitlines()[1:] if line.strip()]
    body = [line for line in lines if not line.startswith("[![")]
    assert body[1].startswith("**") and "pip install edgeproc-core" in body[1]


def test_should_show_at_most_three_badges() -> None:
    assert README.count("[![") <= 3


def test_should_keep_the_sections_in_the_approved_order() -> None:
    positions = [_heading(title) for title in SECTION_ORDER]
    assert positions == sorted(positions)


def test_should_link_the_technical_docs_right_under_the_intro() -> None:
    line = next(line for line in README.splitlines() if line.startswith("**Technical docs:**"))
    assert README.index(line) < _heading("## Try it")
    for doc in TECHNICAL_DOCS:
        assert f"({doc})" in line, f"the technical-docs line does not link {doc}"


def test_should_link_getting_started_from_develop() -> None:
    assert "(docs/GETTING_STARTED.md)" in _section("## Develop")


@pytest.mark.parametrize("word", BANNED)
def test_should_not_use_internal_jargon_or_hype(word: str) -> None:
    pattern = re.compile(rf"\b{re.escape(word)}\b", flags=re.IGNORECASE)
    assert not pattern.search(_prose(README)), f"README uses the banned phrase {word!r}"


def test_banned_word_check_can_fail() -> None:
    """Guard the guard: jargon in a sentence is caught; a command name is not."""
    pattern = re.compile(r"\bgate\b", flags=re.IGNORECASE)
    assert pattern.search(_prose("Run the Gate first."))
    assert not pattern.search(_prose("Run `uv run poe gate`.\n```bash\npoe gate\n```\n"))


def test_should_show_real_output_in_try_it() -> None:
    try_it = _section("## Try it")
    assert "acme sees: [('acme-invoice', 0.0)]" in try_it
    assert "ai.provider.out_of_credits" in try_it


def test_should_explain_how_it_relates_to_the_sibling_projects() -> None:
    for sibling in ("edge-proc", "edge-reco", "@edgeproc/browser", "privacy-core"):
        assert sibling in README, f"README does not say how it relates to {sibling}"


def test_should_state_beta_at_the_released_version_while_pre_1_0() -> None:
    install = _section("## Install")
    version = str(PROJECT["version"])
    assert f"v{version}" in install
    if version.startswith("0."):
        assert "beta" in install.lower()


def test_should_list_every_doc_under_more_detail() -> None:
    more = _section("## More detail")
    docs = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").glob("*.md"))
    root_docs = ("CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "examples/README.md")
    missing = [d for d in (*docs, *root_docs) if f"({d})" not in more]
    assert missing == []


def test_should_link_the_interactive_architecture_map_whose_source_exists() -> None:
    assert re.search(
        r"\[[^\]]*interactive architecture map[^\]]*\]\(docs/architecture/index\.html\)",
        README,
        flags=re.IGNORECASE,
    )
    assert (ROOT / "docs/architecture/runtime.architecture.json").is_file()


def test_should_resolve_every_relative_link_to_a_file_in_the_repo() -> None:
    targets = re.findall(r"\]\(([^)\s]+)\)", README)
    relative = [t for t in targets if not re.match(r"^(?:[a-z]+:|#)", t, flags=re.I)]
    assert relative, "the link extraction matched nothing; this check went blind"
    missing = [t for t in relative if not (ROOT / t.split("#")[0]).exists()]
    assert missing == []


def test_should_end_with_the_mit_license() -> None:
    assert "MIT" in _section("## License")
