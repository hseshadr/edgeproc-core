"""Type definitions for vector management."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Scalar = str | int | float | bool | None
"""Permitted metadata/filter value type. Reject `Dict[str, Any]` typing for records."""

Metadata = Mapping[str, Scalar]
"""Read-only metadata or filter mapping passed across the public API surface."""

DistanceMetric = Literal["cosine", "l2", "inner_product"]
"""Supported vector distance metrics carried through to a downstream backend."""


class VectorEmbedding(BaseModel):
    """Vector embedding with metadata."""

    entity_id: str
    embedding: list[float]
    tenant_id: str | None = None  # Deprecated: use metadata for partition keys.
    metadata: dict[str, Scalar] = Field(default_factory=dict)

    def get_partition_key(self, key_name: str = "tenant_id") -> str | None:
        """
        Get partition key value from embedding.

        First checks metadata[key_name], then falls back to tenant_id for backward compatibility.

        Args:
            key_name: Name of the partition key (e.g., 'tenant_id', 'user_id', 'org_id')

        Returns:
            Partition key value or None
        """
        if key_name in self.metadata:
            value = self.metadata[key_name]
            return str(value) if value is not None else None
        # Backward compatibility: if key_name is 'tenant_id', use the field
        if key_name == "tenant_id":
            return self.tenant_id
        return None


class IndexConfig(BaseModel):
    """Index tuning knobs carried to a downstream backend.

    ``m`` and ``ef_construction`` are HNSW *pass-through* parameters: this
    library ships the partitioning protocol and an in-memory brute-force
    reference index, not an HNSW implementation of its own. A backend that
    implements ``VectorIndex`` (FAISS, pgvector, hnswlib, …) is free to honour
    or ignore them.

    Every knob is a positive count: zero or negative is meaningless for all of
    them, so the bound is enforced here rather than surfacing as a confusing
    backend error (or a silently degenerate index) much later.
    """

    m: int = Field(default=32, gt=0)
    ef_construction: int = Field(default=200, gt=0)
    ef_search: int = Field(default=100, gt=0)
    dimension: int = Field(default=1536, gt=0)
    distance_metric: DistanceMetric = "cosine"


class IndexStats(BaseModel):
    """Index statistics."""

    index_name: str
    vector_count: int
    index_size_mb: float
    tombstone_count: int = 0
    tombstone_percentage: float = 0.0
    build_time_seconds: float | None = None
    last_rebuild_at: str | None = None


@runtime_checkable
class VectorIndex(Protocol):
    """Protocol for vector index implementations."""

    index_name: str
    config: IndexConfig

    async def insert(self, embeddings: list[VectorEmbedding]) -> None:
        """Insert embeddings into index."""
        ...

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Search for nearest neighbors. Returns ``(entity_id, distance)`` tuples."""
        ...

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """Delete embeddings by entity_id, restricted to rows matching ``filters``.

        ``filters`` carries the same partition scope ``search`` receives, so a
        scoped delete can never reach a row a scoped read could not see. An id
        that does not match is left alone — including its tombstone, so one
        partition cannot pre-empt an id another partition has yet to insert.
        Absent (or empty) filters means an unscoped, administrative delete.
        """
        ...

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Get index statistics, counting only rows matching ``filters``.

        Absent (or empty) filters means the physical index's own totals.
        """
        ...

    async def rebuild(self, config: IndexConfig | None = None) -> None:
        """Rebuild index with optional new configuration."""
        ...


class IndexFactory(Protocol):
    """Async factory that constructs a ``VectorIndex`` for a named partition."""

    async def __call__(self, name: str, config: IndexConfig | None = None) -> VectorIndex:
        """Construct (or return) the index instance for ``name``."""
        ...
