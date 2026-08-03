"""Index manager for coordinating partitioned vector indices."""

from __future__ import annotations

from typing import Final

from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexStats,
    Metadata,
    Scalar,
    VectorEmbedding,
)
from edgeproc_core.vector_mgmt.partitioning.strategies import PartitionStrategy

TOMBSTONE_REBUILD_THRESHOLD_PCT: Final[float] = 10.0
"""Tombstone percentage above which a rebuild is triggered."""

INDEX_SIZE_REBUILD_THRESHOLD_MB: Final[float] = 1000.0
"""Index size (MB) above which a rebuild is triggered."""


class IndexManager:
    """Coordinates vector indices through a partitioning strategy."""

    def __init__(
        self,
        partition_strategy: PartitionStrategy,
        default_config: IndexConfig | None = None,
        partition_key_name: str = "tenant_id",
    ) -> None:
        """Wire the manager to a partition strategy and default index config."""
        self.partition_strategy = partition_strategy
        self.default_config = default_config or IndexConfig()
        self.partition_key_name = partition_key_name

    async def insert(
        self,
        embeddings: list[VectorEmbedding],
        partition_key: str | None = None,
    ) -> None:
        """Route ``embeddings`` to partitions and insert into each backing index."""
        partitions = self.partition_strategy.get_partitions(embeddings, partition_key)
        for partition_name, partition_embeddings in partitions.items():
            index = await self.partition_strategy.get_index(partition_name)
            await index.insert(partition_embeddings)

    async def search(
        self,
        query_vector: list[float],
        k: int,
        partition_key: str | None = None,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Search across the selected partitions and return the top ``k`` results."""
        search_filters = self._compose_filters(filters, partition_key)
        partitions = self.partition_strategy.get_search_partitions(partition_key)
        results: list[tuple[str, float]] = []
        for partition_name in partitions:
            index = await self.partition_strategy.get_index(partition_name)
            results.extend(
                await index.search(query_vector, k=k, filters=search_filters, ef_search=ef_search)
            )
        return _merge_top_k(results, k)

    def _compose_filters(
        self, filters: Metadata | None, partition_key: str | None
    ) -> dict[str, Scalar]:
        """Merge caller filters with the partition-key filter when provided."""
        merged: dict[str, Scalar] = dict(filters) if filters else {}
        if partition_key is not None:
            merged[self.partition_key_name] = partition_key
        return merged

    async def delete(
        self,
        entity_ids: list[str],
        partition_key: str | None = None,
    ) -> None:
        """Delete ``entity_ids``, scoped to ``partition_key`` exactly as ``search`` is.

        Selecting the partition is not scoping: bucket collisions are expected by
        design, so the index a key routes to routinely holds other keys' rows too.
        The same filter the read path composes therefore travels with the delete —
        a caller that cannot *see* a row through ``search`` cannot destroy it here.
        """
        delete_filters = self._compose_filters(None, partition_key)
        partitions = self.partition_strategy.get_search_partitions(partition_key)
        for partition_name in partitions:
            index = await self.partition_strategy.get_index(partition_name)
            await index.delete(entity_ids, filters=delete_filters)

    async def get_stats(self, partition_key: str | None = None) -> list[IndexStats]:
        """Return statistics for ``partition_key``'s rows in each partition it routes to.

        Scoped like ``search`` and ``delete``: a colliding neighbour's rows are
        another partition's business and are not counted into this one's totals.
        """
        stats_filters = self._compose_filters(None, partition_key)
        partitions = self.partition_strategy.get_search_partitions(partition_key)
        stats: list[IndexStats] = []
        for partition_name in partitions:
            index = await self.partition_strategy.get_index(partition_name)
            stats.append(await index.get_stats(filters=stats_filters))
        return stats

    async def rebuild_if_needed(
        self,
        partition_key: str | None = None,
        force: bool = False,
    ) -> bool:
        """Trigger a rebuild on the first partition that meets the rebuild criteria.

        Deliberately *not* scoped, unlike ``search``, ``delete`` and ``get_stats``.
        Compaction is a property of a physical index — a slice of a shared index
        cannot be rebuilt on its own — so ``partition_key`` selects which index to
        maintain and nothing more, and the criteria read that index's own totals.
        The visible consequence: a rebuild asked for under one key can be triggered
        by tombstones another key left behind. Reporting is scoped, maintenance is
        physical; ``tests/test_tenant_isolation.py`` pins that asymmetry.

        Iterates partition names (not ``stats.index_name``): a strategy may hand
        the factory a different index name than the partition name it routes by.
        """
        for partition_name in self.partition_strategy.get_search_partitions(partition_key):
            index = await self.partition_strategy.get_index(partition_name)
            if _needs_rebuild(await index.get_stats(), force=force):
                await index.rebuild()
                return True
        return False


def _needs_rebuild(stats: IndexStats, *, force: bool) -> bool:
    """Decide whether an index should be rebuilt based on tombstone load and size."""
    return (
        force
        or stats.tombstone_percentage > TOMBSTONE_REBUILD_THRESHOLD_PCT
        or stats.index_size_mb > INDEX_SIZE_REBUILD_THRESHOLD_MB
    )


def _merge_top_k(raw_results: list[tuple[str, float]], k: int) -> list[tuple[str, float]]:
    """Deduplicate by entity_id (keeping smallest distance) and return the top ``k``."""
    best: dict[str, float] = {}
    for entity_id, distance in raw_results:
        if entity_id not in best or distance < best[entity_id]:
            best[entity_id] = distance
    sorted_results = sorted(best.items(), key=lambda pair: pair[1])
    return sorted_results[:k]
