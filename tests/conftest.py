"""Pytest fixtures and test utilities."""

from collections.abc import Awaitable, Callable

import pytest

from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexStats,
    Metadata,
    VectorEmbedding,
    VectorIndex,
)


def _mock_matches(emb: VectorEmbedding | None, filters: Metadata) -> bool:
    """True when ``emb`` exists and every filter key matches it."""
    if emb is None:
        return False
    return all(
        (emb.get_partition_key("tenant_id") if key == "tenant_id" else emb.metadata.get(key))
        == value
        for key, value in filters.items()
    )


class MockVectorIndex:
    """Mock implementation of VectorIndex protocol for testing."""

    def __init__(self, index_name: str, config: IndexConfig | None = None) -> None:
        self.index_name = index_name
        self.config = config or IndexConfig()
        self._embeddings: dict[str, VectorEmbedding] = {}
        self._deleted: set[str] = set()
        self._stats = IndexStats(
            index_name=index_name,
            vector_count=0,
            index_size_mb=0.0,
            tombstone_count=0,
            tombstone_percentage=0.0,
        )

    async def insert(self, embeddings: list[VectorEmbedding]) -> None:
        """Insert embeddings into mock index."""
        for emb in embeddings:
            if emb.entity_id not in self._deleted:
                self._embeddings[emb.entity_id] = emb
        self._update_stats()

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Mock search - returns all embeddings with fake distances."""
        results: list[tuple[str, float]] = []
        for entity_id, emb in self._embeddings.items():
            if entity_id in self._deleted:
                continue
            # Apply filters if provided
            if filters:
                for key, value in filters.items():
                    if key == "tenant_id" and emb.tenant_id != value:
                        if emb.get_partition_key("tenant_id") != value:
                            continue
                    elif key in emb.metadata and emb.metadata[key] != value:
                        continue
            # Fake distance calculation (just use index for simplicity)
            distance = float(len(results)) * 0.1
            results.append((entity_id, distance))
        # Sort by distance and return top k
        results.sort(key=lambda x: x[1])
        return results[:k]

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Delete embeddings by entity_id, restricted to rows matching ``filters``."""
        for entity_id in entity_ids:
            if filters and not _mock_matches(self._embeddings.get(entity_id), filters):
                continue
            self._deleted.add(entity_id)
            if entity_id in self._embeddings:
                del self._embeddings[entity_id]
        self._update_stats()

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Get index statistics, counting only rows matching ``filters``."""
        if not filters:
            return self._stats
        live = sum(1 for emb in self._embeddings.values() if _mock_matches(emb, filters))
        return self._stats.model_copy(update={"vector_count": live, "index_size_mb": live * 0.001})

    async def rebuild(self, config: IndexConfig | None = None) -> None:
        """Mock rebuild - clears deleted items."""
        self._deleted.clear()
        if config:
            self.config = config
        self._update_stats()

    def _update_stats(self) -> None:
        """Update statistics."""
        total = len(self._embeddings) + len(self._deleted)
        self._stats.vector_count = len(self._embeddings)
        self._stats.tombstone_count = len(self._deleted)
        self._stats.tombstone_percentage = (
            (len(self._deleted) / total * 100.0) if total > 0 else 0.0
        )
        self._stats.index_size_mb = len(self._embeddings) * 0.001  # Fake size


@pytest.fixture
def mock_index_factory() -> Callable[..., Awaitable[VectorIndex]]:
    """Factory function that creates MockVectorIndex instances."""

    async def factory(index_name: str, config: IndexConfig | None = None) -> VectorIndex:
        return MockVectorIndex(index_name, config)

    return factory


@pytest.fixture
def sample_embeddings() -> list[VectorEmbedding]:
    """Sample embeddings for testing."""
    return [
        VectorEmbedding(
            entity_id="entity_1",
            embedding=[0.1, 0.2, 0.3],
            tenant_id="tenant_1",
            metadata={"category": "test"},
        ),
        VectorEmbedding(
            entity_id="entity_2",
            embedding=[0.4, 0.5, 0.6],
            metadata={"tenant_id": "tenant_2", "category": "test"},
        ),
        VectorEmbedding(
            entity_id="entity_3",
            embedding=[0.7, 0.8, 0.9],
            metadata={"user_id": "user_1"},
        ),
    ]


@pytest.fixture
def index_config() -> IndexConfig:
    """Sample index configuration."""
    return IndexConfig(m=32, ef_construction=200, ef_search=100, dimension=1536)
