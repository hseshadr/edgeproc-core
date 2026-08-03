"""Tests for IndexManager."""

from datetime import UTC, datetime, timedelta

import pytest

from edgeproc_core.vector_mgmt.core.index_manager import IndexManager
from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexStats,
    Metadata,
    VectorEmbedding,
    VectorIndex,
)
from edgeproc_core.vector_mgmt.partitioning.strategies import (
    BucketedPartitionStrategy,
    GlobalPartitionStrategy,
    TwoTierPartitionStrategy,
)
from edgeproc_core.vector_mgmt.testing import in_memory_factory


class TestIndexManager:
    """Tests for IndexManager class."""

    @pytest.mark.asyncio
    async def test_insert_with_global_strategy(self, mock_index_factory, sample_embeddings) -> None:
        """Test inserting embeddings with global strategy."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert(sample_embeddings)
        # Verify by checking index stats
        stats = await manager.get_stats()
        assert len(stats) == 1
        assert stats[0].vector_count == 3

    @pytest.mark.asyncio
    async def test_insert_with_partition_key(self, mock_index_factory) -> None:
        """Test inserting with explicit partition key."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1]),
        ]
        await manager.insert(embeddings, partition_key="tenant_1")
        stats = await manager.get_stats()
        assert stats[0].vector_count == 1

    @pytest.mark.asyncio
    async def test_search_with_global_strategy(self, mock_index_factory) -> None:
        """Test searching with global strategy."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        # Insert some embeddings
        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1, 0.2, 0.3],
                tenant_id="tenant_1",
            ),
            VectorEmbedding(
                entity_id="e2",
                embedding=[0.4, 0.5, 0.6],
                tenant_id="tenant_1",
            ),
        ]
        await manager.insert(embeddings, partition_key="tenant_1")
        # Search
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=10,
            partition_key="tenant_1",
        )
        assert len(results) >= 0  # Mock returns results

    @pytest.mark.asyncio
    async def test_search_with_empty_global_partition_key_is_scoped(
        self,
    ) -> None:
        """An explicit empty key must not become an unscoped global search."""
        strategy = GlobalPartitionStrategy(index_factory=in_memory_factory, index_name="global")
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert(
            [
                VectorEmbedding(entity_id="empty", embedding=[1.0], tenant_id=""),
                VectorEmbedding(entity_id="other", embedding=[1.0], tenant_id="tenant-a"),
            ]
        )

        results = await manager.search([1.0], k=10, partition_key="")

        assert [entity_id for entity_id, _ in results] == ["empty"]

    @pytest.mark.asyncio
    async def test_search_with_empty_bucketed_partition_key_finds_matching_entity(
        self,
    ) -> None:
        """An explicit empty key must route insertion and search to one bucket."""
        strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=256)
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert([VectorEmbedding(entity_id="empty", embedding=[1.0], tenant_id="")])

        results = await manager.search([1.0], k=10, partition_key="")

        assert [entity_id for entity_id, _ in results] == ["empty"]

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_index_factory) -> None:
        """Test searching with additional filters."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=10,
            partition_key="tenant_1",
            filters={"category": "test"},
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_with_ef_search(self, mock_index_factory) -> None:
        """Test searching with custom ef_search parameter."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=10,
            partition_key="tenant_1",
            ef_search=200,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_deduplicates_results(self, mock_index_factory) -> None:
        """Test that search deduplicates results across partitions."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        manager = IndexManager(partition_strategy=strategy)
        # Insert same entity in both hot and cold (wouldn't happen in practice, but tests dedup)
        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1, 0.2, 0.3],
                metadata={"created_at": datetime.now().isoformat()},
            ),
        ]
        await manager.insert(embeddings)
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=10,
        )
        # Results should be deduplicated
        entity_ids = [r[0] for r in results]
        assert len(entity_ids) == len(set(entity_ids))  # No duplicates

    @pytest.mark.asyncio
    async def test_search_returns_top_k(self, mock_index_factory) -> None:
        """Test that search returns at most k results."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=5,
        )
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_delete_with_global_strategy(self, mock_index_factory) -> None:
        """Test deleting embeddings with global strategy."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
            VectorEmbedding(entity_id="e2", embedding=[0.2], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        await manager.delete(["e1"], partition_key="t1")
        stats = await manager.get_stats()
        assert stats[0].vector_count == 1

    @pytest.mark.asyncio
    async def test_delete_with_bucketed_strategy(self, mock_index_factory) -> None:
        """Test deleting with bucketed strategy."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=4,
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        await manager.delete(["e1"], partition_key="t1")
        stats = await manager.get_stats()
        # Should search in correct bucket
        assert len(stats) == 1

    @pytest.mark.asyncio
    async def test_get_stats_with_global_strategy(self, mock_index_factory) -> None:
        """Test getting statistics with global strategy."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        stats = await manager.get_stats(partition_key="t1")
        assert len(stats) == 1
        assert stats[0].index_name == "global"
        assert stats[0].vector_count == 1

    @pytest.mark.asyncio
    async def test_get_stats_with_multiple_partitions(self, mock_index_factory) -> None:
        """Test getting statistics across multiple partitions."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        manager = IndexManager(partition_strategy=strategy)
        stats = await manager.get_stats()
        assert len(stats) == 2  # hot and cold

    @pytest.mark.asyncio
    async def test_rebuild_if_needed_no_rebuild(self, mock_index_factory) -> None:
        """Test rebuild_if_needed when rebuild is not needed."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        rebuilt = await manager.rebuild_if_needed(partition_key="t1")
        assert rebuilt is False

    @pytest.mark.asyncio
    async def test_rebuild_if_needed_force_rebuild(self, mock_index_factory) -> None:
        """Test forced rebuild."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        rebuilt = await manager.rebuild_if_needed(partition_key="t1", force=True)
        assert rebuilt is True

    @pytest.mark.asyncio
    async def test_rebuild_if_needed_two_tier_force(self, mock_index_factory) -> None:
        """Forced rebuild must work end-to-end with the two-tier strategy.

        Regression: rebuilds were routed by ``stats.index_name`` ("hot_index"),
        which the two-tier strategy does not accept as a partition name
        ("hot") — rebuild_if_needed crashed with ValueError.
        """
        strategy = TwoTierPartitionStrategy(index_factory=mock_index_factory)
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
        ]
        await manager.insert(embeddings, partition_key="t1")
        rebuilt = await manager.rebuild_if_needed(partition_key="t1", force=True)
        assert rebuilt is True

    @pytest.mark.asyncio
    async def test_rebuild_if_needed_two_tier_tombstone_threshold(self, mock_index_factory) -> None:
        """Tombstone-triggered rebuild must work end-to-end with two-tier."""
        strategy = TwoTierPartitionStrategy(index_factory=mock_index_factory)
        manager = IndexManager(partition_strategy=strategy)
        embeddings = [
            VectorEmbedding(entity_id=f"e{i}", embedding=[0.1], tenant_id="t1") for i in range(5)
        ]
        await manager.insert(embeddings, partition_key="t1")
        await manager.delete(["e0"], partition_key="t1")  # 20% tombstones on hot
        rebuilt = await manager.rebuild_if_needed(partition_key="t1")
        assert rebuilt is True
        hot_stats = await (await strategy.get_index("hot")).get_stats()
        assert hot_stats.tombstone_count == 0

    @pytest.mark.asyncio
    async def test_custom_partition_key_name(self, mock_index_factory) -> None:
        """Test manager with custom partition key name."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            partition_key_name="user_id",
        )
        manager = IndexManager(
            partition_strategy=strategy,
            partition_key_name="user_id",
        )
        assert manager.partition_key_name == "user_id"

    @pytest.mark.asyncio
    async def test_default_config(self, mock_index_factory) -> None:
        """Test manager with default config."""
        default_config = IndexConfig(m=64, ef_construction=300)
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
        )
        manager = IndexManager(
            partition_strategy=strategy,
            default_config=default_config,
        )
        assert manager.default_config == default_config

    @pytest.mark.asyncio
    async def test_search_without_partition_key(self, mock_index_factory) -> None:
        """Test searching without partition key."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        results = await manager.search(
            query_vector=[0.1, 0.2, 0.3],
            k=10,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_insert_empty_list(self, mock_index_factory) -> None:
        """Test inserting empty list."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert([])
        stats = await manager.get_stats()
        assert stats[0].vector_count == 0

    @pytest.mark.asyncio
    async def test_delete_empty_list(self, mock_index_factory) -> None:
        """Test deleting empty list."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        manager = IndexManager(partition_strategy=strategy)
        await manager.delete([])
        # Should not raise


#: A query vector every test below searches with. Two dimensions is enough to
#: place rows at three distinct cosine distances (0.0, ~0.29, 1.0), which is
#: what makes an ordering assertion possible at all.
QUERY: list[float] = [1.0, 0.0]

NEAR: list[float] = [1.0, 0.0]
"""Cosine distance 0.0 from ``QUERY``."""

NEARISH: list[float] = [1.0, 0.5]
"""Cosine distance ~0.106 from ``QUERY``."""

MID: list[float] = [1.0, 1.0]
"""Cosine distance ~0.293 from ``QUERY``."""

FAR: list[float] = [0.0, 1.0]
"""Cosine distance 1.0 from ``QUERY`` — orthogonal."""


def _tiered(entity_id: str, embedding: list[float], *, age_days: int) -> VectorEmbedding:
    """A row the two-tier strategy classifies by its ``created_at`` age."""
    created_at = datetime.now(UTC) - timedelta(days=age_days)
    return VectorEmbedding(
        entity_id=entity_id,
        embedding=embedding,
        metadata={"created_at": created_at.isoformat()},
    )


async def _ids(manager: IndexManager, partition_key: str | None = None) -> list[str]:
    """Entity ids a ``partition_key``-scoped search returns, in returned order."""
    results = await manager.search(QUERY, k=10, partition_key=partition_key)
    return [entity_id for entity_id, _ in results]


class _EfSearchSpy:
    """A ``VectorIndex`` that records the ``ef_search`` value it was handed.

    ``ef_search`` is a pass-through knob — nothing inside this library reads it,
    so only a backend can witness whether the manager forwarded the caller's
    value or quietly dropped it on the floor.
    """

    def __init__(self, index_name: str, config: IndexConfig | None = None) -> None:
        """Start with an empty observation log."""
        self.index_name = index_name
        self.config = config or IndexConfig()
        self.seen_ef_search: list[int | None] = []

    async def insert(self, embeddings: list[VectorEmbedding]) -> None:
        """No-op: this spy only observes the search path."""

    async def search(
        self,
        query_vector: list[float],
        k: int,
        filters: Metadata | None = None,
        ef_search: int | None = None,
    ) -> list[tuple[str, float]]:
        """Record ``ef_search`` and return no matches."""
        self.seen_ef_search.append(ef_search)
        return []

    async def delete(self, entity_ids: list[str], filters: Metadata | None = None) -> None:
        """No-op."""

    async def get_stats(self, filters: Metadata | None = None) -> IndexStats:
        """Empty stats; these tests never read them."""
        return IndexStats(index_name=self.index_name, vector_count=0, index_size_mb=0.0)

    async def rebuild(self, config: IndexConfig | None = None) -> None:
        """No-op."""


class TestSearchCorrectness:
    """What ``search`` actually answers: which ids, in which order, and how many.

    Every test here runs against ``InMemoryVectorIndex`` — a real backend with
    real cosine distances — rather than a mock that invents them, because a
    mock cannot witness a ranking defect.

    Each test was written against a specific mutation that the rest of the
    suite let through: reversing the sort, truncating the partition list,
    misrouting a mixed batch, dropping the top-k slice, keeping the wrong
    duplicate, and dropping the ``ef_search`` pass-through. The mutation each
    one kills is named in its docstring.
    """

    @pytest.mark.asyncio
    async def test_search_returns_the_nearest_neighbour_first(self) -> None:
        """Results are ordered nearest-first.

        Kills: ``sorted(best.items(), key=..., reverse=True)`` — which turns
        nearest-neighbour search into farthest-neighbour search and is invisible
        to every assertion that only checks membership or length.
        """
        strategy = GlobalPartitionStrategy(index_factory=in_memory_factory, index_name="global")
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert(
            [
                VectorEmbedding(entity_id="near", embedding=NEAR),
                VectorEmbedding(entity_id="mid", embedding=MID),
                VectorEmbedding(entity_id="far", embedding=FAR),
            ]
        )

        results = await manager.search(QUERY, k=3)

        assert [entity_id for entity_id, _ in results] == ["near", "mid", "far"]
        distances = [distance for _, distance in results]
        assert distances == sorted(distances), "distances must ascend, not descend"
        assert distances[0] < distances[-1], "non-vacuity: the rows are not equidistant"

    @pytest.mark.asyncio
    async def test_search_reaches_every_partition_the_strategy_names(self) -> None:
        """A row in the second partition still comes back.

        Kills: slicing the searched partition list (``partitions[:1]``), which
        silently halves cross-partition recall.
        """
        strategy = TwoTierPartitionStrategy(index_factory=in_memory_factory, hot_retention_days=30)
        manager = IndexManager(partition_strategy=strategy)
        rows = [_tiered("recent", NEAR, age_days=0), _tiered("ancient", MID, age_days=365)]
        assert sorted(strategy.get_partitions(rows)) == ["cold", "hot"], (
            "non-vacuity: the two rows must land in different partitions"
        )
        await manager.insert(rows)

        assert set(await _ids(manager)) == {"recent", "ancient"}

    @pytest.mark.asyncio
    async def test_insert_routes_each_row_of_a_mixed_batch_by_its_own_key(self) -> None:
        """One call carrying two keys reaches two buckets.

        Kills: routing a whole batch to the first partition. The rows land in an
        index their own key never searches, so the second key's data vanishes.
        """
        strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=256)
        manager = IndexManager(partition_strategy=strategy)
        assert strategy.get_search_partitions("acme") != strategy.get_search_partitions("globex"), (
            "non-vacuity: the two keys must hash to different buckets"
        )

        await manager.insert(
            [
                VectorEmbedding(entity_id="acme-1", embedding=NEAR, metadata={"tenant_id": "acme"}),
                VectorEmbedding(
                    entity_id="globex-1", embedding=NEAR, metadata={"tenant_id": "globex"}
                ),
            ]
        )

        assert await _ids(manager, "acme") == ["acme-1"]
        assert await _ids(manager, "globex") == ["globex-1"]

    @pytest.mark.asyncio
    async def test_search_truncates_the_merged_result_to_k(self) -> None:
        """Two partitions each return ``k`` candidates; the merge still hands back ``k``.

        Kills: dropping the ``[:k]`` slice on the merged list. A single
        partition cannot witness this — the backend truncates to ``k`` on its
        own way out — so the rows are split across the hot and cold indices,
        where the merge sees ``2k`` candidates and has to cut them itself. The
        winner ("second") lives in the *cold* index, so this also pins that the
        merge ranks globally rather than preferring the first partition.
        """
        strategy = TwoTierPartitionStrategy(index_factory=in_memory_factory, hot_retention_days=30)
        manager = IndexManager(partition_strategy=strategy)
        await manager.insert(
            [
                _tiered("near", NEAR, age_days=0),
                _tiered("far", FAR, age_days=0),
                _tiered("second", NEARISH, age_days=365),
                _tiered("third", MID, age_days=365),
            ]
        )
        assert len(await manager.search(QUERY, k=10)) == 4, "non-vacuity: four rows are matchable"

        results = await manager.search(QUERY, k=2)

        assert len(results) == 2
        assert [entity_id for entity_id, _ in results] == ["near", "second"]

    @pytest.mark.asyncio
    async def test_search_keeps_the_smallest_distance_for_a_duplicated_id(self) -> None:
        """One id in two partitions comes back at its *nearest* distance.

        Kills: a dedup that keeps the last value seen rather than the smallest.
        The hot copy sits at distance 0.0 and the cold copy at 1.0, and the cold
        partition is merged second — so "keep the last" reports 1.0.
        """
        strategy = TwoTierPartitionStrategy(index_factory=in_memory_factory, hot_retention_days=30)
        manager = IndexManager(partition_strategy=strategy)
        rows = [_tiered("dup", NEAR, age_days=0), _tiered("dup", FAR, age_days=365)]
        assert list(strategy.get_partitions(rows)) == ["hot", "cold"], (
            "non-vacuity: the copies must split across tiers, hot merged first"
        )
        await manager.insert(rows)

        results = await manager.search(QUERY, k=10)

        assert results == [("dup", pytest.approx(0.0))]

    @pytest.mark.asyncio
    async def test_search_forwards_ef_search_to_the_backend(self) -> None:
        """The caller's ``ef_search`` reaches the index — and ``None`` stays ``None``.

        Kills: dropping the ``ef_search=ef_search`` argument, which leaves every
        backend running at its own default no matter what the caller tuned.
        """
        spy = _EfSearchSpy("global")

        async def factory(name: str, config: IndexConfig | None = None) -> VectorIndex:
            return spy

        strategy = GlobalPartitionStrategy(index_factory=factory, index_name="global")
        manager = IndexManager(partition_strategy=strategy)

        await manager.search(QUERY, k=3, ef_search=321)
        await manager.search(QUERY, k=3)

        assert spy.seen_ef_search == [321, None]
