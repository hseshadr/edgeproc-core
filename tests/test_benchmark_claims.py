"""The published benchmark figures must stay tethered to a real measurement.

The docs once published a best-of-many point estimate that a fresh run did not
reproduce: every figure was optimistic, and across six runs none landed on the
claim. This guards the figures without becoming flaky.

**What this test asserts — and deliberately does not.** It never runs the
benchmark. Timing a workload inside a test suite makes the suite fail on a busy
CI box, which teaches people to ignore it. Instead *both sides are committed
constants*: `REFERENCE` below records what was actually measured (2026-07-20,
Apple M3 Pro, macOS 26.5 arm64, CPython 3.13.5, 20 samples, idle machine), and
the docs carry the figures a reader sees. The test asserts they agree within a
3x band, that no published figure exceeds the benchmark's own budget, and that
ARCHITECTURE and OPERATIONS publish identical numbers.

A 3x band cannot fail on machine variance — nothing is timed here — but it does
catch the real drift: a doc edited to claim an order-of-magnitude better number,
a figure copied to one doc and not the other, or a budget tightened past the
measurement it is supposed to cover. Re-measure and update `REFERENCE` in the
same change whenever the published figures move.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
BAND = 3.0

REFERENCE: dict[str, float] = {
    "routing.p50": 5.8,
    "routing.p95": 6.0,
    "reference search.p50": 19.0,
    "reference search.p95": 19.2,
}
"""Measured 2026-07-20; reproduce with `uv run python benchmarks/benchmark.py`."""

BUDGET_ATTRIBUTE: dict[str, str] = {
    "routing.p50": "PARTITION_P50_MS",
    "routing.p95": "PARTITION_P95_MS",
    "reference search.p50": "SEARCH_P50_MS",
    "reference search.p95": "SEARCH_P95_MS",
}

DOCS = ("docs/ARCHITECTURE.md", "docs/OPERATIONS.md")
FIGURE = re.compile(r"\*\*(routing|reference search) p50 ([\d.]+) ms / p95 ([\d.]+) ms\*\*")
"""The label lives inside the bold marker so the match is unambiguous: prose
mentioning "routing" elsewhere can never be mistaken for a published figure."""


def _benchmark_module() -> ModuleType:
    """Import `benchmarks/benchmark.py` for its committed budget constants."""
    spec = importlib.util.spec_from_file_location("benchmark", ROOT / "benchmarks/benchmark.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _published(document: str) -> dict[str, float]:
    """The `{workload}.{percentile} -> milliseconds` figures a document claims."""
    text = (ROOT / document).read_text(encoding="utf-8")
    return {
        f"{workload}.{percentile}": float(value)
        for workload, p50, p95 in FIGURE.findall(text)
        for percentile, value in (("p50", p50), ("p95", p95))
    }


def _within_band(published: float, reference: float) -> bool:
    """Whether a published figure sits inside the 3x band around the measurement."""
    return reference / BAND <= published <= reference * BAND


@pytest.mark.parametrize("document", DOCS)
def test_document_publishes_every_expected_figure(document: str) -> None:
    """Non-vacuity: a doc that stopped stating its numbers must fail, not pass."""
    assert set(_published(document)) == set(REFERENCE)


@pytest.mark.parametrize("document", DOCS)
def test_published_figures_match_the_recorded_measurement(document: str) -> None:
    """Each published figure agrees with what was actually measured, within 3x."""
    drifted = [
        f"{document}: {label} claims {value} ms, measurement was {REFERENCE[label]} ms"
        for label, value in _published(document).items()
        if not _within_band(value, REFERENCE[label])
    ]

    assert drifted == []


def test_both_documents_publish_the_same_figures() -> None:
    """A number updated in one doc and forgotten in the other is drift."""
    assert _published("docs/ARCHITECTURE.md") == _published("docs/OPERATIONS.md")


@pytest.mark.parametrize(("label", "attribute"), sorted(BUDGET_ATTRIBUTE.items()))
def test_measurement_stays_within_the_benchmark_budget(label: str, attribute: str) -> None:
    """The benchmark's own budget must still cover the measurement it guards."""
    budget = getattr(_benchmark_module(), attribute)

    assert REFERENCE[label] <= budget, f"{label} measured {REFERENCE[label]} ms, budget {budget} ms"


@pytest.mark.parametrize(
    ("published", "expected"),
    [(19.0, True), (57.0, True), (57.1, False), (6.4, True), (6.3, False), (0.5, False)],
)
def test_the_band_predicate_rejects_an_implausible_claim(published: float, expected: bool) -> None:
    """Non-vacuity: show the band actually excludes values, at both edges of 3x."""
    assert _within_band(published, 19.0) is expected
