"""The round trip: what you insert under a key, you can read, count and delete under it.

``search``, ``delete`` and ``get_stats`` all filter on row *metadata*, while
routing may fall back to the ``partition_key`` *argument*. A row inserted with an
argument-only key therefore landed in the right physical index and was still
invisible through its own key: uncounted by its stats, and undeletable by its
scoped delete. Only an unscoped administrative delete could reach it — which is
the worst shape a data-integrity defect can take, because nothing raises and
nothing looks wrong until someone asks where their row went.

These tests pin the round trip for all three shipped strategies and for a
consumer keyed on something other than ``tenant_id`` — the shape that bit
hardest, because ``VectorEmbedding.get_partition_key`` only falls back to the
deprecated ``tenant_id`` field when the key is literally named ``tenant_id``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from edgeproc_core import BucketedPartitionStrategy, IndexManager
from edgeproc_core.vector_mgmt.core.types import VectorEmbedding
from edgeproc_core.vector_mgmt.partitioning.strategies import (
    GlobalPartitionStrategy,
    PartitionStrategy,
    TwoTierPartitionStrategy,
)
from edgeproc_core.vector_mgmt.testing import in_memory_factory

VECTOR = [0.1, 0.2, 0.3, 0.4]
"""One shared vector: every row matches equally well, so only the partition
filter — never distance ranking — can decide what comes back."""

StrategyBuilder = Callable[[], PartitionStrategy]

STRATEGIES: list[object] = [
    pytest.param(
        lambda: GlobalPartitionStrategy(index_factory=in_memory_factory, index_name="global"),
        id="global",
    ),
    pytest.param(
        lambda: BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=256),
        id="bucketed",
    ),
    pytest.param(
        lambda: TwoTierPartitionStrategy(index_factory=in_memory_factory),
        id="two_tier",
    ),
]


def _orphan(entity_id: str) -> VectorEmbedding:
    """A row carrying no partition key of its own — the argument is its only scope."""
    return VectorEmbedding(entity_id=entity_id, embedding=VECTOR)


async def _ids(manager: IndexManager, partition_key: str | None) -> list[str]:
    """Every entity id a ``partition_key``-scoped read can reach, sorted."""
    results = await manager.search(VECTOR, k=100, partition_key=partition_key)
    return sorted(entity_id for entity_id, _ in results)


async def _physical_rows(strategy: PartitionStrategy, partition_key: str) -> int:
    """Live rows in the physical indices ``partition_key`` routes to, unfiltered.

    A scoped read cannot tell "deleted" from "was never visible to this key" —
    both return nothing. Only the physical index's own unscoped totals can, so
    that is what the delete guard asserts against.
    """
    total = 0
    for partition_name in strategy.get_search_partitions(partition_key):
        index = await strategy.get_index(partition_name)
        total += (await index.get_stats()).vector_count
    return total


@pytest.mark.parametrize("build_strategy", STRATEGIES)
async def test_should_find_a_row_when_its_only_key_came_from_the_insert_argument(
    build_strategy: StrategyBuilder,
) -> None:
    """A row inserted under ``partition_key`` is visible to that key's search."""
    manager = IndexManager(partition_strategy=build_strategy())

    await manager.insert([_orphan("orphan")], partition_key="acme")

    assert await _ids(manager, "acme") == ["orphan"]


@pytest.mark.parametrize("build_strategy", STRATEGIES)
async def test_should_count_a_row_when_its_only_key_came_from_the_insert_argument(
    build_strategy: StrategyBuilder,
) -> None:
    """That same row is counted by that key's scoped stats."""
    manager = IndexManager(partition_strategy=build_strategy())

    await manager.insert([_orphan("orphan")], partition_key="acme")

    assert sum(s.vector_count for s in await manager.get_stats(partition_key="acme")) == 1


@pytest.mark.parametrize("build_strategy", STRATEGIES)
async def test_should_delete_a_row_when_its_only_key_came_from_the_insert_argument(
    build_strategy: StrategyBuilder,
) -> None:
    """That same row is destroyable by that key's scoped delete.

    The physical-row count is the load-bearing assertion: before the fix the
    scoped delete matched nothing and the row survived, reachable only by an
    unscoped administrative delete. A scoped read alone cannot tell "deleted"
    from "was never visible in the first place" — both return nothing — so this
    reads the backing index's own unfiltered totals instead.
    """
    strategy = build_strategy()
    manager = IndexManager(partition_strategy=strategy)
    await manager.insert([_orphan("orphan")], partition_key="acme")
    assert await _physical_rows(strategy, "acme") == 1, "non-vacuity: the row was there to lose"

    await manager.delete(["orphan"], partition_key="acme")

    assert await _ids(manager, "acme") == []
    assert await _physical_rows(strategy, "acme") == 0, "the row survived a scoped delete"


async def test_should_round_trip_a_consumer_keyed_on_something_other_than_tenant_id() -> None:
    """``org_id`` round-trips, even on a row still carrying a legacy ``tenant_id``.

    ``VectorEmbedding.get_partition_key`` falls back to the deprecated
    ``tenant_id`` field only when the key is named ``tenant_id``, so an
    ``org_id`` consumer had no fallback at all and lost the row outright.
    """
    strategy = BucketedPartitionStrategy(
        index_factory=in_memory_factory, num_buckets=256, partition_key_name="org_id"
    )
    manager = IndexManager(partition_strategy=strategy, partition_key_name="org_id")
    row = VectorEmbedding(entity_id="row", embedding=VECTOR, metadata={"tenant_id": "legacy"})

    await manager.insert([row], partition_key="acme")

    assert await _ids(manager, "acme") == ["row"]


async def test_should_keep_the_key_a_row_already_carries() -> None:
    """The argument fills a gap; it never overwrites a key the row supplied.

    The row says ``acme`` and the call says ``globex``. Routing already follows
    the row, so the metadata must too — otherwise the stamp would file the row
    under a key whose bucket it does not even live in.
    """
    strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=256)
    manager = IndexManager(partition_strategy=strategy)
    row = VectorEmbedding(entity_id="row", embedding=VECTOR, metadata={"tenant_id": "acme"})

    await manager.insert([row], partition_key="globex")

    assert await _ids(manager, "acme") == ["row"]
    assert await _ids(manager, "globex") == []


async def test_should_leave_the_callers_embedding_unmutated() -> None:
    """The caller's object comes back untouched; the stamp lands on a copy."""
    manager = IndexManager(
        partition_strategy=GlobalPartitionStrategy(
            index_factory=in_memory_factory, index_name="global"
        )
    )
    row = _orphan("row")

    await manager.insert([row], partition_key="acme")

    assert row.metadata == {}


async def test_should_leave_a_row_unkeyed_when_the_insert_supplied_no_key() -> None:
    """No argument means no scope to stamp — the stated administrative boundary.

    An unkeyed row inserted without a key stays unkeyed and is reachable only
    through an unscoped read. The library never guesses a scope nobody supplied.
    """
    manager = IndexManager(
        partition_strategy=GlobalPartitionStrategy(
            index_factory=in_memory_factory, index_name="global"
        )
    )

    await manager.insert([_orphan("orphan")])

    assert await _ids(manager, None) == ["orphan"]
    assert await _ids(manager, "acme") == []


async def test_should_not_expose_a_stamped_row_to_a_different_key() -> None:
    """Stamping must not widen a scope. Forced collision, so only the filter can isolate.

    ``num_buckets=1`` puts both rows in one physical index, so if the metadata
    stamp were wrong or absent the two keys would see each other's rows.
    """
    strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=1)
    manager = IndexManager(partition_strategy=strategy)
    assert strategy.get_search_partitions("acme") == strategy.get_search_partitions("globex"), (
        "non-vacuity: both keys must share one physical index"
    )

    await manager.insert([_orphan("acme-row")], partition_key="acme")
    await manager.insert([_orphan("globex-row")], partition_key="globex")

    assert await _ids(manager, "acme") == ["acme-row"]
    assert await _ids(manager, "globex") == ["globex-row"]


def test_bucketed_get_partitions_still_routes_an_unkeyed_row_by_the_argument() -> None:
    """The strategy's own argument fallback — the line the stamp exists to make honest.

    ``get_partitions`` is public surface and a custom extractor can still return
    ``None``, so the fallback stays reachable. What changes is that a row routed
    this way through ``IndexManager`` now also carries the key it was routed by.
    """
    strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=256)
    expected = strategy.get_search_partitions("acme")

    partitions = strategy.get_partitions([_orphan("orphan")], partition_key="acme")

    assert list(partitions) == expected
    assert [emb.entity_id for emb in partitions[expected[0]]] == ["orphan"]
