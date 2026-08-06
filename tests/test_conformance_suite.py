"""The conformance suite must be able to fail — pinned against backends that break it.

``edgeproc_core.vector_mgmt.conformance`` exists so a third-party ``VectorIndex``
implementer can prove their backend *applies* the ``filters`` argument 0.3.0 added
to ``delete`` and ``get_stats``. A suite that cannot fail an accept-and-ignore
backend would be the very defect it was written to catch — a guard that reports
success without being able to fail — so every check it runs is paired below with a
backend that breaks exactly that one property, and asserted to be rejected by name.

The headline case is ``_IgnoresFiltersIndex``: the correct signature, ``filters``
accepted and never used. It type-checks, it passes a backend's own suite, and it
silently reintroduces the cross-partition data destruction 0.3.0 was cut to fix.

Two of the backends below — ``_OrsMultiKeyFiltersIndex`` and
``_EmptyFiltersMatchNothingIndex`` — were **certified conformant** by the suite as it
shipped through 0.4.0, and both leak. They are kept here permanently for the same
reason as the rest: a conformance suite is only worth its name while a known-bad
implementation is on file that it is required to reject.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from edgeproc_core.vector_mgmt.conformance import assert_vector_index_conformance
from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexFactory,
    IndexStats,
    Metadata,
    VectorEmbedding,
    VectorIndex,
)
from edgeproc_core.vector_mgmt.testing import (
    InMemoryVectorIndex,
    _field_matches,
    in_memory_factory,
)
from tests.conftest import MockVectorIndex


class _IgnoresFiltersIndex(InMemoryVectorIndex):
    """The defect the suite exists for: ``filters`` accepted and never applied.

    Source-compatible with the 0.3.0 protocol, green under ``mypy --strict``, and
    a cross-tenant delete.
    """

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Accept ``filters``, drop it on the floor, delete across every partition."""
        await super().delete(entity_ids)

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Accept ``filters``, drop it on the floor, count the neighbour's rows too."""
        return await super().get_stats()


class _RefusesScopedDeleteIndex(InMemoryVectorIndex):
    """Spares the neighbour by never honouring a scoped delete at all."""

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Silently no-op whenever a scope is supplied."""
        if filters:
            return
        await super().delete(entity_ids)


class _IgnoresUnscopedDeleteIndex(InMemoryVectorIndex):
    """Honours scoped deletes but silently drops administrative, unscoped ones."""

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Silently no-op whenever no scope is supplied."""
        if not filters:
            return
        await super().delete(entity_ids, filters=filters)


class _UnfilteredSearchIndex(InMemoryVectorIndex):
    """A scoped read that returns everyone's rows."""

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Accept ``filters``, drop it on the floor, return every row."""
        return await super().search(query_vector, k=k, ef_search=ef_search)


class _MiscountingStatsIndex(InMemoryVectorIndex):
    """Stats that never see the rows: the physical total is wrong before any filter is."""

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Report an empty index no matter what it holds."""
        stats = await super().get_stats(filters)
        return stats.model_copy(update={"vector_count": 0})


class _DropsInsertsIndex(InMemoryVectorIndex):
    """Accepts rows and keeps none: nothing the suite writes can be read back."""

    async def insert(self, embeddings: list[VectorEmbedding]) -> None:
        """Accept the rows and discard them."""
        return None


def _matches_any(emb: VectorEmbedding, filters: Metadata | None) -> bool:
    """``testing._matches`` with its quantifier flipped: ``all`` -> ``any``.

    That one word is the entire defect. Under a *single-key* filter — every filter
    the suite passed before 0.4.1 — ``any`` and ``all`` agree on every input, which
    is exactly why a backend built on it was certified conformant.
    """
    if not filters:
        return True
    return any(_field_matches(emb, key, value) for key, value in filters.items())


def _single_key_views(filters: Metadata | None) -> list[Metadata | None]:
    """``filters`` split into one single-key mapping per key.

    Matching the union of these is what ORing the keys means.
    """
    if not filters:
        return [filters]
    return [{key: value} for key, value in filters.items()]


class _OrsMultiKeyFiltersIndex(InMemoryVectorIndex):
    """Multi-key filters ORed instead of ANDed: matching *any* one key is in scope.

    Indistinguishable from a conformant backend under a one-key filter, and a
    cross-partition leak under two. ``IndexManager._compose_filters`` merges the
    caller's filters *with* the partition key, so every scoped call that carries a
    filter of its own is a two-key filter — and under OR the partition key stops
    narrowing anything. ``{tenant_id: a, tier: hot}`` returns all of ``a``'s rows
    plus every *other* tenant's hot ones, and deletes them too.
    """

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Union of the single-key searches: matching one key is enough."""
        found: dict[str, float] = {}
        for view in _single_key_views(filters):
            found.update(await super().search(query_vector, k, view, ef_search))
        return sorted(found.items(), key=lambda pair: pair[1])[:k]

    def _out_of_scope(self, entity_id: str, filters: Metadata | None) -> bool:
        """A row is in a scoped delete's reach as soon as one key matches."""
        if not filters:
            return False
        held = self._embeddings.get(entity_id)
        return held is None or not _matches_any(held, filters)

    def _live_count(self, filters: Metadata | None) -> int:
        """Count every row matching any one key."""
        return sum(1 for emb in self._embeddings.values() if _matches_any(emb, filters))


def _is_empty_scope(filters: Metadata | None) -> bool:
    """An empty filter mapping, told apart from no mapping at all."""
    return filters is not None and len(filters) == 0


class _EmptyFiltersMatchNothingIndex(InMemoryVectorIndex):
    """``filters={}`` read as a scope no row can satisfy — the empty-IN-clause bug.

    A backend that renders the mapping into SQL arrives here by accident: zero keys
    becomes ``WHERE id IN ()``, which matches nothing. Nothing about that is exotic,
    and nothing about it is visible either — ``IndexManager._compose_filters(None,
    None)`` returns ``{}``, never ``None``, so *every* unscoped call the library
    makes travels through this exact shape. An administrative delete silently
    removes no rows and raises nothing.
    """

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Return nothing for the empty scope."""
        if _is_empty_scope(filters):
            return []
        return await super().search(query_vector, k, filters, ef_search)

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Delete nothing for the empty scope."""
        if _is_empty_scope(filters):
            return
        await super().delete(entity_ids, filters)

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Count nothing for the empty scope."""
        stats = await super().get_stats(filters)
        if _is_empty_scope(filters):
            return stats.model_copy(update={"vector_count": 0})
        return stats


#: Any class constructible the way an ``IndexFactory`` constructs one. Wider than
#: ``type[InMemoryVectorIndex]`` because ``MockVectorIndex`` is graded here too and
#: does not inherit from it.
_Backend = Callable[[str, IndexConfig | None], VectorIndex]


def _factory_for(index_type: _Backend) -> IndexFactory:
    """An ``IndexFactory`` handing out fresh instances of one backend."""

    async def factory(name: str, config: IndexConfig | None = None) -> VectorIndex:
        return index_type(name, config)

    return factory


async def _rejection_report(index_type: type[InMemoryVectorIndex]) -> str:
    """Run the suite against a broken backend and return the failure it reported."""
    with pytest.raises(AssertionError) as excinfo:
        await assert_vector_index_conformance(_factory_for(index_type))
    return str(excinfo.value)


async def test_the_shipped_reference_backend_is_conformant() -> None:
    """``InMemoryVectorIndex`` — the backend this package ships — passes its own suite.

    Non-vacuity for every rejection below: if the suite failed everything, the
    ``pytest.raises`` assertions would pass while proving nothing.
    """
    await assert_vector_index_conformance(in_memory_factory)


async def test_the_reference_backend_is_conformant_under_a_custom_partition_key() -> None:
    """Isolation is a property of the partition key, not of the name ``tenant_id``."""
    await assert_vector_index_conformance(in_memory_factory, partition_key_name="org_id")


async def test_the_mock_backend_the_rest_of_the_suite_runs_on_is_conformant() -> None:
    """``MockVectorIndex`` is a second backend, and nothing had ever certified it.

    ``tests/test_index_manager.py`` grades the manager's scoping against this class,
    so an unconformant mock would let the manager's own isolation tests pass on a
    backend that leaks — the suite existed and its second-largest consumer never ran
    it. Wiring it here costs one test and removes that whole category of doubt.
    """
    await assert_vector_index_conformance(_factory_for(MockVectorIndex))


async def test_a_backend_that_accepts_filters_and_ignores_them_is_rejected() -> None:
    """The headline case: correct signature, ``filters`` never applied.

    Both halves of the 0.3.0 break must be named — a suite that caught only the
    delete would let a scoped ``get_stats`` keep counting the neighbour's rows.
    """
    report = await _rejection_report(_IgnoresFiltersIndex)

    assert "scoped_delete_spares_other_partitions" in report
    assert "scoped_stats_count_only_their_partition" in report


async def test_ignoring_filters_is_not_reported_as_a_wholesale_failure() -> None:
    """The report must localise the defect, not smear it across every check.

    An accept-and-ignore backend inserts, searches and deletes correctly; only its
    scoped writes are broken. A suite that failed all thirteen checks here would be
    telling the implementer nothing about where to look.

    The count moved 2-of-7 -> 4-of-13 in 0.4.1, and both halves of that move are
    load-bearing. Six checks were added; two of them — the multi-key delete and the
    multi-key stats count — are *newly* failed by this same backend, because ignoring
    ``filters`` ignores a two-key filter just as thoroughly as a one-key one. The
    2-of-7 was never wrong; it was measuring a suite that asked fewer questions.
    """
    report = await _rejection_report(_IgnoresFiltersIndex)

    assert report.startswith("4 of 13 VectorIndex conformance checks failed")


async def test_a_backend_that_refuses_every_scoped_delete_is_rejected() -> None:
    """Non-vacuity: a backend cannot pass by never deleting anything."""
    report = await _rejection_report(_RefusesScopedDeleteIndex)

    assert "scoped_delete_removes_its_own_rows" in report


async def test_a_backend_that_drops_unscoped_deletes_is_rejected() -> None:
    """The documented boundary: no filters means an administrative, cross-partition delete."""
    report = await _rejection_report(_IgnoresUnscopedDeleteIndex)

    assert "unscoped_delete_is_administrative" in report


async def test_a_backend_whose_search_ignores_filters_is_rejected() -> None:
    """The read-side promise the write side mirrors — broken alone, caught alone."""
    assert "search_applies_filters" in await _rejection_report(_UnfilteredSearchIndex)


async def test_a_backend_whose_stats_never_see_the_rows_is_rejected() -> None:
    """A wrong physical total is caught before any filter is blamed for it."""
    assert "unscoped_stats_report_the_physical_total" in await _rejection_report(
        _MiscountingStatsIndex
    )


async def test_a_backend_that_keeps_nothing_is_rejected_before_anything_else() -> None:
    """Guard the guard: the suite must refuse to grade a backend it cannot observe."""
    report = await _rejection_report(_DropsInsertsIndex)

    assert "rows_are_readable_back" in report


async def test_a_backend_that_ors_multi_key_filters_is_rejected() -> None:
    """A one-key filter means the same thing under AND and under OR.

    Every filter this suite passed through 0.4.0 had exactly one key, so it was
    structurally incapable of telling the two apart, and it certified
    ``_OrsMultiKeyFiltersIndex`` as conformant. ``IndexManager`` composes the
    partition key *into* the caller's filters, so an ORing backend hands a scoped
    search someone else's rows and lets a scoped delete destroy them.
    """
    report = await _rejection_report(_OrsMultiKeyFiltersIndex)

    assert "search_ands_multi_key_filters" in report
    assert "multi_key_delete_ands_its_filters" in report
    assert "multi_key_stats_count_the_intersection" in report


async def test_a_backend_that_reads_empty_filters_as_a_scope_is_rejected() -> None:
    """``filters={}`` is no scope, and it is the shape the library actually sends.

    Through 0.4.0 the suite called ``delete(ids)`` and ``delete(ids, filters={k: v})``
    and never ``delete(ids, filters={})`` — so the one call shape ``IndexManager``
    composes for every *unscoped* operation went ungraded, and
    ``_EmptyFiltersMatchNothingIndex`` was certified conformant while silently
    no-opping every administrative delete made through the library.
    """
    report = await _rejection_report(_EmptyFiltersMatchNothingIndex)

    assert "empty_filters_search_is_unscoped" in report
    assert "empty_filters_delete_is_administrative" in report
    assert "empty_filters_stats_report_the_physical_total" in report


async def test_the_suite_refuses_to_partition_on_its_own_reserved_key() -> None:
    """The second dimension the suite seeds cannot also be the caller's key.

    It would overwrite the tier on every row, silently collapsing the multi-key
    checks into single-key ones — the exact blindness this release closed. A suite
    that cannot grade the property must say so, not grade a weaker one.
    """
    with pytest.raises(ValueError, match="conformance_tier"):
        await assert_vector_index_conformance(
            in_memory_factory, partition_key_name="conformance_tier"
        )


async def test_the_report_points_the_implementer_at_the_contract() -> None:
    """A failure message that does not say what to fix is a bug report nobody can action."""
    report = await _rejection_report(_IgnoresFiltersIndex)

    assert "accept" in report and "apply" in report
    assert "0.3.0" in report
