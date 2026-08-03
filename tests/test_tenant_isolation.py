"""The headline promise: nobody ever sees anyone else's results.

The README's central claim is that partitioning keeps tenants apart. Bucketing
makes collisions *inevitable* by design: once tenants outnumber buckets, two
tenants share one physical index. Proving isolation only on disjoint partitions
proves nothing about the case the design actually creates.

These tests force the worst case — ``num_buckets=1``, so every partition key
collides into a single index — and assert that a tenant-scoped read still
returns that tenant's rows and nothing else. Each isolation test is paired with
a non-vacuity assertion that the collision genuinely happened, so the suite can
never pass because the tenants quietly landed in separate buckets.
"""

from __future__ import annotations

import pytest

from edgeproc_core import BucketedPartitionStrategy, IndexManager
from edgeproc_core.vector_mgmt.core.types import VectorEmbedding
from edgeproc_core.vector_mgmt.testing import in_memory_factory

VECTOR = [0.1, 0.2, 0.3, 0.4]
"""One shared vector: every row is an equally good match, so only the partition
filter — never distance ranking — can be what keeps a tenant's rows out."""


def _embeddings(tenant: str, count: int, key_name: str = "tenant_id") -> list[VectorEmbedding]:
    """``count`` identically-embedded rows tagged for ``tenant``."""
    return [
        VectorEmbedding(entity_id=f"{tenant}-{i}", embedding=VECTOR, metadata={key_name: tenant})
        for i in range(count)
    ]


def _single_bucket(key_name: str = "tenant_id") -> BucketedPartitionStrategy:
    """A strategy whose every partition key collides into one physical index."""
    return BucketedPartitionStrategy(
        index_factory=in_memory_factory, num_buckets=1, partition_key_name=key_name
    )


async def _visible_ids(manager: IndexManager, tenant: str) -> set[str]:
    """Every entity id a ``tenant``-scoped read can still reach."""
    results = await manager.search(VECTOR, k=100, partition_key=tenant)
    return {entity_id for entity_id, _ in results}


def test_forced_collision_actually_puts_both_tenants_in_one_index() -> None:
    """Non-vacuity guard: the isolation tests below really do share an index."""
    strategy = _single_bucket()
    assert strategy.get_search_partitions("tenant_a") == strategy.get_search_partitions("tenant_b")

    partitions = strategy.get_partitions(_embeddings("tenant_a", 2) + _embeddings("tenant_b", 2))

    assert len(partitions) == 1, "expected one shared bucket, got a disjoint split"
    assert len(next(iter(partitions.values()))) == 4


@pytest.mark.parametrize(("mine", "theirs"), [("tenant_a", "tenant_b"), ("tenant_b", "tenant_a")])
async def test_search_under_forced_collision_returns_only_the_querying_tenant(
    mine: str, theirs: str
) -> None:
    """Colliding tenants share one index; a scoped search still sees only its own."""
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings(mine, 3))
    await manager.insert(_embeddings(theirs, 3))

    results = await manager.search(VECTOR, k=10, partition_key=mine)
    returned = {entity_id for entity_id, _ in results}

    assert returned == {f"{mine}-0", f"{mine}-1", f"{mine}-2"}
    assert not any(entity_id.startswith(theirs) for entity_id in returned)


async def test_search_under_forced_collision_isolates_a_custom_partition_key() -> None:
    """Isolation is a property of the partition key, not of the name ``tenant_id``."""
    manager = IndexManager(
        partition_strategy=_single_bucket("user_id"), partition_key_name="user_id"
    )
    await manager.insert(_embeddings("user_a", 2, "user_id"))
    await manager.insert(_embeddings("user_b", 2, "user_id"))

    returned = {
        entity_id for entity_id, _ in await manager.search(VECTOR, k=10, partition_key="user_a")
    }

    assert returned == {"user_a-0", "user_a-1"}


async def test_collision_does_not_shadow_rows_that_share_an_entity_id_prefix() -> None:
    """A colliding neighbour cannot displace a tenant's own rows from its top-k."""
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 50))

    returned = await manager.search(VECTOR, k=2, partition_key="tenant_a")

    assert {entity_id for entity_id, _ in returned} == {"tenant_a-0", "tenant_a-1"}


async def test_an_unscoped_search_is_explicitly_not_isolated() -> None:
    """The stated boundary: isolation comes from the partition key the caller passes.

    Searching with ``partition_key=None`` applies no filter and is documented as
    an administrative, cross-tenant read. Pinning it here keeps the promise
    honest — the library isolates *scoped* reads, and never claims to guess
    scope the caller did not supply.
    """
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 2))

    returned = {entity_id for entity_id, _ in await manager.search(VECTOR, k=10)}

    assert len(returned) == 4


async def test_should_leave_a_colliding_tenants_rows_intact_when_a_delete_is_scoped() -> None:
    """A scoped delete may not reach across the partition key it was scoped to.

    Given two tenants forced into one physical index, and rows only ``tenant_b`` owns,
    When ``tenant_a`` scopes a delete at those ids,
    Then every one of ``tenant_b``'s rows survives.
    """
    strategy = _single_bucket()
    manager = IndexManager(partition_strategy=strategy)
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 3))
    theirs = ["tenant_b-0", "tenant_b-1"]
    assert strategy.get_search_partitions("tenant_a") == strategy.get_search_partitions("tenant_b")
    assert set(theirs) <= await _visible_ids(manager, "tenant_b"), "rows were never there to lose"

    await manager.delete(theirs, partition_key="tenant_a")

    assert await _visible_ids(manager, "tenant_b") == {"tenant_b-0", "tenant_b-1", "tenant_b-2"}


async def test_should_remove_the_scoping_tenants_own_rows_when_a_delete_is_scoped() -> None:
    """Non-vacuity for the guard above: scoping a delete must not disarm it.

    Given the same shared index,
    When ``tenant_a`` scopes a delete at a row it does own,
    Then that row is gone and ``tenant_b``'s rows are untouched.
    """
    strategy = _single_bucket()
    manager = IndexManager(partition_strategy=strategy)
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 3))
    assert strategy.get_search_partitions("tenant_a") == strategy.get_search_partitions("tenant_b")

    await manager.delete(["tenant_a-0"], partition_key="tenant_a")

    assert await _visible_ids(manager, "tenant_a") == {"tenant_a-1"}
    assert len(await _visible_ids(manager, "tenant_b")) == 3


async def test_should_count_only_the_scoping_tenants_vectors_when_stats_are_scoped() -> None:
    """``get_stats`` reports on a partition, not on whoever else shares its index.

    Given 2 ``tenant_a`` rows colliding with 3 ``tenant_b`` rows in one index,
    When stats are read scoped to ``tenant_a``,
    Then the count is 2 — while the unscoped read still shows all 5 in that one
    index, which is what proves the collision really happened.
    """
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 3))

    scoped = await manager.get_stats(partition_key="tenant_a")

    assert [stat.vector_count for stat in scoped] == [2]
    assert [stat.vector_count for stat in await manager.get_stats()] == [5]


async def test_should_not_tombstone_a_future_row_when_a_scoped_delete_misses() -> None:
    """A scoped delete that owns nothing must leave nothing behind either.

    Given ``tenant_a`` scopes a delete at an id no partition holds yet,
    When ``tenant_b`` later inserts exactly that id,
    Then ``tenant_b`` can read it back — no tombstone was planted in its name.
    """
    strategy = _single_bucket()
    manager = IndexManager(partition_strategy=strategy)
    await manager.insert(_embeddings("tenant_a", 1))
    assert strategy.get_search_partitions("tenant_a") == strategy.get_search_partitions("tenant_b")

    await manager.delete(["tenant_b-0"], partition_key="tenant_a")
    await manager.insert(_embeddings("tenant_b", 1))

    assert await _visible_ids(manager, "tenant_b") == {"tenant_b-0"}


async def test_should_delete_across_tenants_when_no_partition_key_is_given() -> None:
    """The stated boundary, mirroring the unscoped read.

    With no partition key there is no filter, so an unscoped delete is an
    administrative, cross-partition write — the library isolates *scoped* calls
    and never guesses a scope the caller did not supply.

    Given rows from both tenants in one index,
    When ids belonging to both are deleted with no scope,
    Then both are gone — which is also the proof that the guards above are a
    filter and not a delete that quietly stopped working.
    """
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings("tenant_a", 2))
    await manager.insert(_embeddings("tenant_b", 2))

    await manager.delete(["tenant_a-0", "tenant_b-0"])

    assert await _visible_ids(manager, "tenant_a") == {"tenant_a-1"}
    assert await _visible_ids(manager, "tenant_b") == {"tenant_b-1"}


async def test_should_rebuild_the_whole_shared_index_when_maintenance_is_scoped() -> None:
    """Rebuild stays physical, and that asymmetry is deliberate, not an oversight.

    Compaction is a property of a physical index: a slice of a shared index
    cannot be rebuilt on its own, so ``partition_key`` here selects *which index
    to maintain* and nothing more. Reporting is scoped; maintenance is physical.

    Given tombstones that only ``tenant_b`` created,
    When ``tenant_a`` asks whether its index needs a rebuild,
    Then it does — even though ``tenant_a``'s own scoped stats show no tombstones.
    """
    manager = IndexManager(partition_strategy=_single_bucket())
    await manager.insert(_embeddings("tenant_a", 1))
    await manager.insert(_embeddings("tenant_b", 9))
    await manager.delete(["tenant_b-0", "tenant_b-1"], partition_key="tenant_b")

    assert (await manager.get_stats(partition_key="tenant_a"))[0].tombstone_percentage == 0.0
    assert await manager.rebuild_if_needed(partition_key="tenant_a") is True
