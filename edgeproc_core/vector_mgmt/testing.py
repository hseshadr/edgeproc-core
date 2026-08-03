"""In-memory ``VectorIndex`` reference implementation for tests and examples.

This is **not** a production index. It exists so that:

- the test suite can exercise ``IndexManager`` and the partition strategies
  against a real, conformant ``VectorIndex`` (not a mock that lies);
- the ``examples/`` directory can run end-to-end with zero external setup —
  a cold reader can ``python examples/basic_usage.py`` and see real output.

Production consumers should implement the ``VectorIndex`` protocol against
their actual backend (FAISS, pgvector, hnswlib, …). See ``edge-proc``'s
``LocalVecIndex`` for a FAISS-backed example.
"""

from __future__ import annotations

import math

from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexStats,
    Metadata,
    Scalar,
    VectorEmbedding,
    VectorIndex,
)


class InMemoryVectorIndex:
    """In-memory ``VectorIndex`` implementation. Tests and examples only.

    Insertion is a dict update; search is a linear scan with cosine distance.
    Suitable for unit tests and demo runs; not for production load.
    """

    def __init__(self, index_name: str, config: IndexConfig | None = None) -> None:
        """Initialise an empty in-memory index."""
        self.index_name = index_name
        self.config = config or IndexConfig()
        self._embeddings: dict[str, VectorEmbedding] = {}
        #: Tombstoned id -> the row it removed, or ``None`` when the id was never
        #: held. Keeping the row is what lets a scoped ``get_stats`` attribute a
        #: tombstone to the partition it came from instead of to whoever asks.
        self._deleted: dict[str, VectorEmbedding | None] = {}

    async def insert(self, embeddings: list[VectorEmbedding]) -> None:
        """Insert embeddings, ignoring any whose id has been tombstoned."""
        for emb in embeddings:
            if emb.entity_id not in self._deleted:
                self._embeddings[emb.entity_id] = emb

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Linear-scan cosine search returning ``(entity_id, distance)`` pairs."""
        _ = ef_search  # signature parity with the protocol; unused here.
        scored = [
            (eid, _cosine_distance(query_vector, emb.embedding))
            for eid, emb in self._embeddings.items()
            if _matches(emb, filters)
        ]
        scored.sort(key=lambda pair: pair[1])
        return scored[:k]

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Tombstone the given ``entity_ids`` that ``filters`` matches, and drop them."""
        for entity_id in entity_ids:
            if self._out_of_scope(entity_id, filters):
                continue
            self._deleted[entity_id] = self._embeddings.pop(entity_id, None)

    def _out_of_scope(self, entity_id: str, filters: Metadata | None) -> bool:
        """True when a scoped delete must leave ``entity_id`` entirely alone.

        An id this index does not hold matches no filter, so a scoped delete
        cannot tombstone it — otherwise one partition could block an id another
        partition has not inserted yet.
        """
        if not filters:
            return False
        held = self._embeddings.get(entity_id)
        return held is None or not _matches(held, filters)

    def _live_count(self, filters: Metadata | None) -> int:
        """Live rows ``filters`` matches (all of them when unscoped)."""
        return sum(1 for emb in self._embeddings.values() if _matches(emb, filters))

    def _tombstone_count(self, filters: Metadata | None) -> int:
        """Tombstones attributable to ``filters`` (all of them when unscoped)."""
        return sum(1 for emb in self._deleted.values() if _tombstone_matches(emb, filters))

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Return stats for the rows ``filters`` matches: count, tombstone share, fake size."""
        live = self._live_count(filters)
        tombstoned = self._tombstone_count(filters)
        total = live + tombstoned
        return IndexStats(
            index_name=self.index_name,
            vector_count=live,
            index_size_mb=live * 0.001,
            tombstone_count=tombstoned,
            tombstone_percentage=(tombstoned / total * 100.0) if total > 0 else 0.0,
        )

    async def rebuild(self, config: IndexConfig | None = None) -> None:
        """Drop tombstones and adopt ``config`` if supplied."""
        self._deleted.clear()
        if config is not None:
            self.config = config


async def in_memory_factory(name: str, config: IndexConfig | None = None) -> VectorIndex:
    """Drop-in ``IndexFactory`` that returns a fresh ``InMemoryVectorIndex``."""
    return InMemoryVectorIndex(name, config)


def _tombstone_matches(removed: VectorEmbedding | None, filters: Metadata | None) -> bool:
    """Attribute a tombstone to a scope only when the row it removed is known.

    An id tombstoned without ever being held belongs to no partition, so it
    counts in the physical total and in no scoped one.
    """
    if not filters:
        return True
    return removed is not None and _matches(removed, filters)


def _matches(emb: VectorEmbedding, filters: Metadata | None) -> bool:
    """Return ``True`` when every filter key matches metadata or ``tenant_id``."""
    if not filters:
        return True
    return all(_field_matches(emb, key, value) for key, value in filters.items())


def _field_matches(emb: VectorEmbedding, key: str, value: Scalar) -> bool:
    """Match a single filter key against ``tenant_id`` or a metadata entry."""
    if key == "tenant_id":
        return emb.get_partition_key("tenant_id") == value
    return emb.metadata.get(key) == value


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine *distance* (1 - cosine similarity); zero vectors → distance 1.0."""
    norm = _l2(a) * _l2(b)
    if norm == 0.0:
        return 1.0
    return 1.0 - _dot(a, b) / norm


def _dot(a: list[float], b: list[float]) -> float:
    """Dot product of two equal-length vectors."""
    total = 0.0
    for x, y in zip(a, b, strict=False):
        total += x * y
    return total


def _l2(v: list[float]) -> float:
    """L2 norm (Euclidean length) of ``v``."""
    total = 0.0
    for x in v:
        total += x * x
    return math.sqrt(total)
