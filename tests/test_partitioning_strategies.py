"""Tests for partitioning strategies."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    VectorEmbedding,
    VectorIndex,
)
from edgeproc_core.vector_mgmt.partitioning.strategies import (
    _TIER_FACTORY_NAMES,
    BucketedPartitionStrategy,
    GlobalPartitionStrategy,
    PartitionStrategy,
    TwoTierPartitionStrategy,
)
from edgeproc_core.vector_mgmt.testing import in_memory_factory
from tests.conftest import MockVectorIndex


class TestGlobalPartitionStrategy:
    """Tests for GlobalPartitionStrategy."""

    @pytest.mark.asyncio
    async def test_get_partitions_all_to_global(self, mock_index_factory) -> None:
        """Test that all embeddings go to single global partition."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
            VectorEmbedding(entity_id="e2", embedding=[0.2], tenant_id="t2"),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert len(partitions) == 1
        assert "global" in partitions
        assert len(partitions["global"]) == 2

    @pytest.mark.asyncio
    async def test_get_search_partitions_returns_global(self, mock_index_factory) -> None:
        """Test that search always returns global partition."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        partitions = strategy.get_search_partitions("tenant_1")
        assert partitions == ["global"]
        partitions = strategy.get_search_partitions(None)
        assert partitions == ["global"]

    @pytest.mark.asyncio
    async def test_get_index_creates_singleton(self, mock_index_factory) -> None:
        """Test that get_index returns same instance."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            index_name="global",
        )
        index1 = await strategy.get_index("global")
        index2 = await strategy.get_index("global")
        assert index1 is index2
        assert index1.index_name == "global"

    @pytest.mark.asyncio
    async def test_custom_partition_key_name(self, mock_index_factory) -> None:
        """Test global strategy with custom partition key name."""
        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            partition_key_name="user_id",
        )
        assert strategy.partition_key_name == "user_id"

    @pytest.mark.asyncio
    async def test_custom_partition_key_extractor(self, mock_index_factory) -> None:
        """Test global strategy with custom partition key extractor."""

        def extractor(emb: VectorEmbedding) -> str | None:
            return emb.metadata.get("custom_key")

        strategy = GlobalPartitionStrategy(
            index_factory=mock_index_factory,
            partition_key_extractor=extractor,
        )
        emb = VectorEmbedding(
            entity_id="e1",
            embedding=[0.1],
            metadata={"custom_key": "custom_value"},
        )
        key = strategy._extract_key(emb)
        assert key == "custom_value"


class TestBucketedPartitionStrategy:
    """Tests for BucketedPartitionStrategy."""

    @pytest.mark.parametrize("num_buckets", [0, -1])
    def test_should_reject_non_positive_bucket_count_when_constructed(
        self,
        mock_index_factory,
        num_buckets: int,
    ) -> None:
        """A bad count must fail at the boundary, not during later routing."""
        # Given a valid index factory and an invalid bucket count
        # When the bucket strategy is constructed
        # Then it fails closed before any key can reach modulo routing
        with pytest.raises(ValueError, match="num_buckets must be at least 1"):
            BucketedPartitionStrategy(
                index_factory=mock_index_factory,
                num_buckets=num_buckets,
            )

    @pytest.mark.asyncio
    async def test_get_partitions_distributes_to_buckets(self, mock_index_factory) -> None:
        """Test that embeddings are distributed across buckets."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=4,
        )
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], tenant_id="t1"),
            VectorEmbedding(entity_id="e2", embedding=[0.2], tenant_id="t2"),
            VectorEmbedding(entity_id="e3", embedding=[0.3], tenant_id="t3"),
        ]
        partitions = strategy.get_partitions(embeddings)
        # All embeddings should be partitioned (may be in same or different buckets)
        total = sum(len(embs) for embs in partitions.values())
        assert total == 3

    @pytest.mark.asyncio
    async def test_get_search_partitions_returns_correct_bucket(self, mock_index_factory) -> None:
        """Test that search returns correct bucket for partition key."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=256,
        )
        partitions = strategy.get_search_partitions("tenant_123")
        assert len(partitions) == 1
        assert partitions[0].startswith("bucket_")

    @pytest.mark.asyncio
    async def test_get_search_partitions_none_key(self, mock_index_factory) -> None:
        """Test that None partition key goes to bucket 0."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=256,
        )
        partitions = strategy.get_search_partitions(None)
        assert partitions == ["bucket_0"]

    @pytest.mark.asyncio
    async def test_get_index_creates_per_bucket(self, mock_index_factory) -> None:
        """Test that get_index creates separate indices per bucket."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=4,
        )
        index1 = await strategy.get_index("bucket_0")
        index2 = await strategy.get_index("bucket_1")
        index3 = await strategy.get_index("bucket_0")
        assert index1 is index3  # Same bucket, same instance
        assert index1 is not index2  # Different buckets

    @pytest.mark.asyncio
    async def test_bucket_id_consistency(self, mock_index_factory) -> None:
        """Test that same partition key always maps to same bucket."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=256,
        )
        bucket1 = strategy._get_bucket_id("tenant_123")
        bucket2 = strategy._get_bucket_id("tenant_123")
        assert bucket1 == bucket2

    @pytest.mark.asyncio
    async def test_partition_key_from_metadata(self, mock_index_factory) -> None:
        """Test that partition key is extracted from embeddings."""
        strategy = BucketedPartitionStrategy(
            index_factory=mock_index_factory,
            num_buckets=4,
            partition_key_name="user_id",
        )
        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1],
                metadata={"user_id": "user_1"},
            ),
            VectorEmbedding(
                entity_id="e2",
                embedding=[0.2],
                metadata={"user_id": "user_2"},
            ),
        ]
        partitions = strategy.get_partitions(embeddings)
        total = sum(len(embs) for embs in partitions.values())
        assert total == 2


class TestBucketRoutingDeterminism:
    """Persisted bucket routing must be stable across processes.

    Python's builtin ``hash()`` is randomized per process (PYTHONHASHSEED), so
    any strategy that persists bucket assignments must NOT use it. These tests
    pin the routing to a process-independent digest.
    """

    _BUCKET_SCRIPT = (
        "from edgeproc_core.vector_mgmt.partitioning.strategies import "
        "BucketedPartitionStrategy\n"
        "strategy = BucketedPartitionStrategy(index_factory=None, num_buckets=1024)\n"
        "keys = [f'tenant_{i}' for i in range(32)] + ['\\u00fcn\\u00efcode-tenant']\n"
        "print([strategy.get_search_partitions(key) for key in keys])\n"
    )

    def _buckets_with_hash_seed(self, seed: str) -> str:
        """Run bucket routing in a fresh interpreter with a fixed PYTHONHASHSEED."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", self._BUCKET_SCRIPT],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        return result.stdout

    def test_same_key_routes_to_same_bucket_across_processes(self) -> None:
        """The same keys must route to the same buckets under different hash seeds."""
        assert self._buckets_with_hash_seed("1") == self._buckets_with_hash_seed("2")

    @pytest.mark.asyncio
    async def test_bucket_assignment_is_pinned(self, mock_index_factory) -> None:
        """Golden values: persisted bucket assignments must never drift."""
        strategy = BucketedPartitionStrategy(index_factory=mock_index_factory, num_buckets=256)
        assert strategy.get_search_partitions("tenant_123") == ["bucket_48"]
        assert strategy.get_search_partitions("ünïcode-tenant") == ["bucket_60"]


class TestConcurrentIndexCreation:
    """Concurrent lazy index creation must not lose writes.

    Without a lock, two coroutines can both observe "no index yet", both await
    the factory, and the loser's index (plus any writes already applied to it)
    is silently replaced. The factory must run exactly once per partition and
    every concurrent caller must receive the same instance.
    """

    @staticmethod
    def _counting_factory() -> tuple[list[str], object]:
        """Return a (created_names, factory) pair whose factory yields mid-creation."""
        created: list[str] = []

        async def factory(index_name: str, config: IndexConfig | None = None) -> VectorIndex:
            await asyncio.sleep(0)  # yield control mid-creation to expose the race
            created.append(index_name)
            return MockVectorIndex(index_name, config)

        return created, factory

    async def _assert_single_creation(
        self, strategy: PartitionStrategy, partition_name: str, created: list[str]
    ) -> None:
        """Hammer get_index concurrently; require one instance and one factory call."""
        indices = await asyncio.gather(*(strategy.get_index(partition_name) for _ in range(10)))
        assert all(index is indices[0] for index in indices)
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_global_strategy_creates_exactly_one_index(self) -> None:
        """Concurrent get_index on the global strategy must create one index."""
        created, factory = self._counting_factory()
        strategy = GlobalPartitionStrategy(index_factory=factory)
        await self._assert_single_creation(strategy, "global_index", created)

    @pytest.mark.asyncio
    async def test_bucketed_strategy_creates_exactly_one_index_per_bucket(self) -> None:
        """Concurrent get_index on one bucket must create one index for it."""
        created, factory = self._counting_factory()
        strategy = BucketedPartitionStrategy(index_factory=factory, num_buckets=4)
        await self._assert_single_creation(strategy, "bucket_0", created)

    @pytest.mark.asyncio
    async def test_two_tier_strategy_creates_exactly_one_index_per_tier(self) -> None:
        """Concurrent get_index on the hot tier must create one index for it."""
        created, factory = self._counting_factory()
        strategy = TwoTierPartitionStrategy(index_factory=factory)
        await self._assert_single_creation(strategy, "hot", created)


class TestSearchPartitionsAreRoutable:
    """Every partition a strategy says to search must be one it can build an index for.

    This is the invariant defect (c) violated: ``TwoTierPartitionStrategy``
    searched ``"hot"``/``"cold"`` while a stale ``IndexManager`` routed rebuilds
    by the factory-facing index name (``"hot_index"``), which ``get_index``
    rejects. ``get_search_partitions`` is now derived from the same
    ``_TIER_FACTORY_NAMES`` table ``get_index`` routes with, so the search set
    and the routing table cannot drift apart.
    """

    @pytest.mark.asyncio
    async def test_every_searched_partition_is_routable(self, mock_index_factory) -> None:
        """No strategy may name a search partition its own get_index would reject."""
        strategies: list[PartitionStrategy] = [
            GlobalPartitionStrategy(index_factory=mock_index_factory),
            BucketedPartitionStrategy(index_factory=mock_index_factory, num_buckets=8),
            TwoTierPartitionStrategy(index_factory=mock_index_factory),
        ]
        for strategy in strategies:
            for partition_name in strategy.get_search_partitions("tenant_1"):
                index = await strategy.get_index(partition_name)  # must not raise
                assert index is not None

    @pytest.mark.asyncio
    async def test_two_tier_search_set_matches_factory_tiers(self, mock_index_factory) -> None:
        """The two-tier search set is exactly the keys of the routing table."""
        strategy = TwoTierPartitionStrategy(index_factory=mock_index_factory)
        assert set(strategy.get_search_partitions()) == set(_TIER_FACTORY_NAMES)


class TestTwoTierPartitionStrategy:
    """Tests for TwoTierPartitionStrategy."""

    @pytest.mark.asyncio
    async def test_get_partitions_hot_cold_split(self, mock_index_factory) -> None:
        """Test that embeddings are split into hot and cold based on date."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        now = datetime.now()
        recent_date = (now - timedelta(days=10)).isoformat()
        old_date = (now - timedelta(days=40)).isoformat()

        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1],
                metadata={"created_at": recent_date},
            ),
            VectorEmbedding(
                entity_id="e2",
                embedding=[0.2],
                metadata={"created_at": old_date},
            ),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert "hot" in partitions
        assert "cold" in partitions
        assert len(partitions["hot"]) == 1
        assert len(partitions["cold"]) == 1
        assert partitions["hot"][0].entity_id == "e1"
        assert partitions["cold"][0].entity_id == "e2"

    @pytest.mark.asyncio
    async def test_get_partitions_no_date_defaults_to_hot(self, mock_index_factory) -> None:
        """Test that embeddings without date default to hot."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], metadata={}),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert "hot" in partitions
        assert len(partitions["hot"]) == 1

    @pytest.mark.asyncio
    async def test_get_partitions_invalid_date_defaults_to_cold(self, mock_index_factory) -> None:
        """Test that invalid date strings default to cold."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1],
                metadata={"created_at": "invalid-date"},
            ),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert "cold" in partitions
        assert len(partitions["cold"]) == 1

    @pytest.mark.asyncio
    async def test_get_partitions_timezone_aware_timestamps(self, mock_index_factory) -> None:
        """Timezone-aware ``created_at`` values must classify without raising.

        Regression: the cutoff was naive, so aware timestamps (e.g. a "Z" or
        "+00:00" suffix) raised TypeError on comparison.
        """
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        now = datetime.now(UTC)
        recent_aware = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        old_aware = (now - timedelta(days=40)).isoformat()

        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], metadata={"created_at": recent_aware}),
            VectorEmbedding(entity_id="e2", embedding=[0.2], metadata={"created_at": old_aware}),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert partitions["hot"][0].entity_id == "e1"
        assert partitions["cold"][0].entity_id == "e2"

    @pytest.mark.asyncio
    async def test_get_partitions_mixed_naive_and_aware_timestamps(
        self, mock_index_factory
    ) -> None:
        """Naive timestamps are interpreted as UTC and mix safely with aware ones."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        now = datetime.now(UTC)
        naive_recent = (now - timedelta(days=10)).replace(tzinfo=None).isoformat()
        aware_old = (now - timedelta(days=40)).isoformat()

        embeddings = [
            VectorEmbedding(entity_id="e1", embedding=[0.1], metadata={"created_at": naive_recent}),
            VectorEmbedding(entity_id="e2", embedding=[0.2], metadata={"created_at": aware_old}),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert partitions["hot"][0].entity_id == "e1"
        assert partitions["cold"][0].entity_id == "e2"

    @pytest.mark.asyncio
    async def test_get_search_partitions_returns_both(self, mock_index_factory) -> None:
        """Test that search returns both hot and cold partitions."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        partitions = strategy.get_search_partitions("tenant_1")
        assert set(partitions) == {"hot", "cold"}

    @pytest.mark.asyncio
    async def test_get_index_creates_hot_cold(self, mock_index_factory) -> None:
        """Test that get_index creates separate hot and cold indices."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        hot_index = await strategy.get_index("hot")
        cold_index = await strategy.get_index("cold")
        assert hot_index.index_name == "hot_index"
        assert cold_index.index_name == "cold_index"
        assert hot_index is not cold_index

    @pytest.mark.asyncio
    async def test_get_index_unknown_partition_raises(self, mock_index_factory) -> None:
        """Test that unknown partition name raises ValueError."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=30,
        )
        with pytest.raises(ValueError, match="Unknown partition"):
            await strategy.get_index("unknown")

    @pytest.mark.asyncio
    async def test_custom_retention_days(self, mock_index_factory) -> None:
        """Test custom hot retention days."""
        strategy = TwoTierPartitionStrategy(
            index_factory=mock_index_factory,
            hot_retention_days=7,
        )
        now = datetime.now()
        recent_date = (now - timedelta(days=5)).isoformat()
        old_date = (now - timedelta(days=10)).isoformat()

        embeddings = [
            VectorEmbedding(
                entity_id="e1",
                embedding=[0.1],
                metadata={"created_at": recent_date},
            ),
            VectorEmbedding(
                entity_id="e2",
                embedding=[0.2],
                metadata={"created_at": old_date},
            ),
        ]
        partitions = strategy.get_partitions(embeddings)
        assert partitions["hot"][0].entity_id == "e1"
        assert partitions["cold"][0].entity_id == "e2"


class TestConfigReachesTheFactory:
    """A strategy's ``config`` must reach the index it builds.

    Nothing else in the suite reads the config back off a constructed index, so
    dropping ``config=`` from a factory call is invisible: the index quietly
    builds at ``IndexConfig()``'s 1536-dimension default and a 7-dimension
    deployment is silently wrong. These pin the pass-through for all three
    strategies, not just the one where the hole was found.
    """

    @pytest.mark.parametrize(
        ("build_strategy", "partition_name"),
        [
            (
                lambda config: GlobalPartitionStrategy(
                    index_factory=in_memory_factory, index_name="global", config=config
                ),
                "global",
            ),
            (
                lambda config: BucketedPartitionStrategy(
                    index_factory=in_memory_factory, num_buckets=4, config=config
                ),
                "bucket_0",
            ),
            (
                lambda config: TwoTierPartitionStrategy(
                    index_factory=in_memory_factory, config=config
                ),
                "hot",
            ),
        ],
        ids=["global", "bucketed", "two_tier"],
    )
    @pytest.mark.asyncio
    async def test_get_index_hands_the_configured_config_to_the_factory(
        self, build_strategy, partition_name: str
    ) -> None:
        """The index is constructed with the caller's config, not a default one."""
        config = IndexConfig(dimension=7, ef_search=13, distance_metric="l2")

        index = await build_strategy(config).get_index(partition_name)

        assert index.config == config
        assert index.config.dimension == 7, "a dropped config= silently builds at 1536"
        assert index.config.ef_search == 13
        assert index.config.distance_metric == "l2"

    @pytest.mark.asyncio
    async def test_default_config_is_not_the_configured_one(self) -> None:
        """Non-vacuity: the assertions above would pass on any config if 7 were the default."""
        assert IndexConfig().dimension == 1536
        assert IndexConfig().ef_search == 100
        assert IndexConfig().distance_metric == "cosine"
