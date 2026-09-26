"""Fail the gate when docs/ARCHITECTURE.md's published coverage figures drift from reality.

docs/ARCHITECTURE.md states two specific numbers. Numbers in prose rot silently: the suite
grows, the real figure moves, and the doc keeps advertising the old one. This
script re-derives both figures from the `coverage.xml` that the test run just
wrote and compares them to what docs/ARCHITECTURE.md claims.

It runs as a gate step *after* `pytest`, not as a test, because pytest writes
`coverage.xml` at session end — a test reading that file mid-session would only
ever see the previous run's numbers, and would find no file at all on a fresh
checkout.

Usage: ``python scripts/check_coverage_claim.py``
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_XML = ROOT / "coverage.xml"
CLAIMS_DOC = ROOT / "docs" / "ARCHITECTURE.md"

#: Coverage rates are rounded to two decimals in prose; allow only that much slack.
TOLERANCE_PERCENT = 0.005

TOTAL_CLAIM = re.compile(r"(\d+\.\d+)%\s+coverage measured with branches enabled")
STATEMENT_CLAIM = re.compile(r"(\d+\.\d+)% of statements")
BRANCH_CLAIM = re.compile(r"(\d+\.\d+)% of branches")

#: The rates live as attributes on the Cobertura root element. We read them with
#: a regex rather than an XML parser deliberately: stdlib XML parsers carry XXE
#: and entity-expansion attack surface, and pulling in `defusedxml` to read a
#: handful of floats out of one machine-generated tag is not a trade worth making.
_ROOT_ATTR = r'<coverage\b[^>]*\b{attribute}="([0-9.]+)"'


@dataclass(frozen=True)
class Claim:
    """One coverage figure docs/ARCHITECTURE.md publishes, and the rate that backs it."""

    label: str
    published: float
    measured: float

    @property
    def drifted(self) -> bool:
        return abs(self.published - self.measured) > TOLERANCE_PERCENT

    def describe(self) -> str:
        verdict = "DRIFTED" if self.drifted else "ok"
        return (
            f"  {verdict:>7}  {self.label:<10} "
            f"doc says {self.published:.2f}%, coverage.xml measures {self.measured:.2f}%"
        )


def _root_attr(report: str, attribute: str) -> float:
    match = re.search(_ROOT_ATTR.format(attribute=attribute), report)
    if match is None:
        _die(f"coverage.xml has no {attribute!r} on its root element; cannot verify the claim.")
    return float(match.group(1))


def _measured_rates() -> tuple[float, float, float]:
    """Return (total, statement, branch) coverage percentages from the last test run.

    `total` is what `--cov-fail-under` gates on when `--cov-branch` is enabled:
    coverage.py pools statements and branches into one ratio. It is therefore
    neither the statement rate nor the branch rate, which is exactly the
    confusion this check exists to prevent.
    """
    if not COVERAGE_XML.exists():
        _die(f"{COVERAGE_XML.name} not found. Run the test suite before this check.")
    report = COVERAGE_XML.read_text(encoding="utf-8")

    covered = _root_attr(report, "lines-covered") + _root_attr(report, "branches-covered")
    valid = _root_attr(report, "lines-valid") + _root_attr(report, "branches-valid")
    return (
        covered / valid * 100,
        _root_attr(report, "line-rate") * 100,
        _root_attr(report, "branch-rate") * 100,
    )


def _published_rate(pattern: re.Pattern[str], label: str, readme: str) -> float:
    match = pattern.search(readme)
    if match is None:
        _die(f"{CLAIMS_DOC.name} no longer publishes a {label} coverage figure; check is blind.")
    return float(match.group(1))


def _die(message: str) -> NoReturn:
    print(f"coverage claim check: {message}", file=sys.stderr)
    raise SystemExit(1)


def _collect_claims() -> list[Claim]:
    total, statement, branch = _measured_rates()
    readme = CLAIMS_DOC.read_text(encoding="utf-8")
    return [
        Claim("total", _published_rate(TOTAL_CLAIM, "total", readme), total),
        Claim("statement", _published_rate(STATEMENT_CLAIM, "statement", readme), statement),
        Claim("branch", _published_rate(BRANCH_CLAIM, "branch", readme), branch),
    ]


def main() -> int:
    claims = _collect_claims()
    for claim in claims:
        print(claim.describe())

    drifted = [claim for claim in claims if claim.drifted]
    if drifted:
        names = ", ".join(claim.label for claim in drifted)
        print(
            f"\nFAIL: ARCHITECTURE.md {names} coverage claim(s) no longer match the measured run.\n"
            f"Update docs/ARCHITECTURE.md to the measured figure — do not lower the gate.",
            file=sys.stderr,
        )
        return 1

    print("\nOK: ARCHITECTURE.md coverage claims match the measured run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
