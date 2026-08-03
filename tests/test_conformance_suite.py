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
"""

from __future__ import annotations

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
from edgeproc_core.vector_mgmt.testing import InMemoryVectorIndex, in_memory_factory


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


def _factory_for(index_type: type[InMemoryVectorIndex]) -> IndexFactory:
    """An ``IndexFactory`` handing out fresh instances of one broken backend."""

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

    An accept-and-ignore backend inserts, searches and deletes correctly; only the
    two scoped writes are broken. A suite that failed all seven checks here would
    be telling the implementer nothing about where to look.
    """
    report = await _rejection_report(_IgnoresFiltersIndex)

    assert report.startswith("2 of 7 VectorIndex conformance checks failed")


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


async def test_the_report_points_the_implementer_at_the_contract() -> None:
    """A failure message that does not say what to fix is a bug report nobody can action."""
    report = await _rejection_report(_IgnoresFiltersIndex)

    assert "accept" in report and "apply" in report
    assert "0.3.0" in report
