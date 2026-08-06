"""Conformance suite for third-party ``VectorIndex`` backends.

**Point this at your backend before you ship it.** 0.3.0 added a
``filters: Metadata | None = None`` argument to ``VectorIndex.delete`` and
``VectorIndex.get_stats``, and ``IndexManager`` passes the partition scope through
it. Because the argument has a default, a backend that accepts ``filters`` and
never applies it still type-checks, still passes its own tests — and silently
destroys the neighbouring partition's rows on every scoped delete. Nothing about
that failure is visible to a compiler, a linter, or an import-level API check.

This module is the missing check. It seeds one physical index with two partitions'
rows (every row carrying the *same* vector, so distance ranking can never be what
separates them — the same forced-collision idea as
``tests/test_tenant_isolation.py``) and then asserts that ``delete`` and
``get_stats`` genuinely *apply* the filter they accept.

Run it against your backend::

    import asyncio

    from edgeproc_core.vector_mgmt.conformance import assert_vector_index_conformance
    from my_project import MyVectorIndex


    async def my_factory(name, config=None):
        return MyVectorIndex(name, config)


    asyncio.run(assert_vector_index_conformance(my_factory))

Or, as a test (this is the recommended home for it)::

    async def test_my_backend_is_conformant():
        await assert_vector_index_conformance(my_factory)

It raises ``AssertionError`` listing every property your backend breaks, and
returns ``None`` when it breaks none.

Two blind spots closed in 0.4.1, both of which had certified a leaking backend:

- **Every filter the suite passed carried exactly one key.** One key means the same
  thing whether a backend ANDs or ORs, so the suite could not tell the two apart and
  graded an ORing backend as conformant. ``IndexManager`` composes the partition key
  *into* the caller's filters, so under OR the partition key stops narrowing anything:
  a scoped search returns the neighbour's rows and a scoped delete destroys them. The
  suite now seeds a second metadata dimension and grades a two-key filter.
- **``filters={}`` was never passed.** ``IndexManager._compose_filters(None, None)``
  returns ``{}``, never ``None``, so an empty mapping is the shape *every* unscoped
  call the library makes actually travels in — and it was the one shape ungraded. A
  backend reading it as "a scope matching no row" (the empty ``IN ()`` clause a SQL
  renderer produces by accident) silently no-ops every administrative delete.

Scope, stated so nothing here implies a proof it does not make: this suite grades
``insert``, ``search``, ``delete`` and ``get_stats``'s ``vector_count`` under a
partition filter. It does not grade recall, latency, ``rebuild``, or how a backend
attributes tombstones to a scope — those are backend-specific and untested here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from edgeproc_core.vector_mgmt.core.types import (
    IndexConfig,
    IndexFactory,
    Metadata,
    Scalar,
    VectorEmbedding,
    VectorIndex,
)

__all__ = ["assert_vector_index_conformance"]

_VECTOR: Final[list[float]] = [0.1, 0.2, 0.3, 0.4]
"""One shared vector: every row is an equally good match, so only the filter —
never distance ranking — can be what keeps a partition's rows out of a result."""

_MINE: Final = "conformance_partition_a"
_THEIRS: Final = "conformance_partition_b"
_MINE_ROWS: Final = 2
_THEIRS_ROWS: Final = 3
_TOTAL_ROWS: Final = _MINE_ROWS + _THEIRS_ROWS

_K: Final = 100
"""Larger than the seeded row count, so top-k truncation can never pass for a filter."""

_TIER_KEY: Final = "conformance_tier"
"""A second metadata dimension, orthogonal to the partition key.

One filter key cannot distinguish AND from OR — ``{a: x}`` selects the same rows
under either rule — so a single-key suite grades a property it cannot observe. Two
keys can, and this is the second one.
"""

_HOT: Final = "hot"
_COLD: Final = "cold"

_UNSCOPED: Final[dict[str, Scalar]] = {}
"""The empty filter mapping: no scope at all, exactly like passing none.

Not a hypothetical shape. ``IndexManager._compose_filters(None, None)`` returns
``{}``, so every unscoped ``search``/``delete``/``get_stats`` the library issues
arrives at a backend looking precisely like this.
"""


def _ids(partition: str, count: int) -> set[str]:
    """The entity ids ``_rows`` generates for one partition."""
    return {f"{partition}-{i}" for i in range(count)}


_ALL_IDS: Final[set[str]] = _ids(_MINE, _MINE_ROWS) | _ids(_THEIRS, _THEIRS_ROWS)


def _tier(i: int) -> str:
    """Row 0 of each partition is hot and the rest cold — the second dimension's values."""
    return _HOT if i == 0 else _COLD


_AND_MATCHES: Final[set[str]] = {f"{_MINE}-{i}" for i in range(_MINE_ROWS) if _tier(i) == _HOT}
"""The rows matching *both* keys of ``_and_filter``, derived from the same ``_tier``
that seeds them so the expectation cannot drift away from the fixture.

Under OR that filter instead matches every ``_MINE`` row *and* ``_THEIRS``'s hot one
— a strictly wider set, in another partition. That gap is what the checks read.
"""


def _rows(partition: str, count: int, key: str) -> list[VectorEmbedding]:
    """``count`` identically-embedded rows tagged for ``partition`` under ``key``."""
    return [
        VectorEmbedding(
            entity_id=f"{partition}-{i}",
            embedding=_VECTOR,
            metadata={key: partition, _TIER_KEY: _tier(i)},
        )
        for i in range(count)
    ]


def _and_filter(key: str) -> dict[str, Scalar]:
    """A two-key filter whose AND selects exactly ``_AND_MATCHES`` and whose OR does not."""
    return {key: _MINE, _TIER_KEY: _HOT}


async def _seeded(factory: IndexFactory, key: str) -> VectorIndex:
    """A fresh index holding both partitions' rows — one physical index, two scopes.

    Every check gets its own index: a check that inherited another's tombstones
    would be grading history instead of the property it names.
    """
    index = await factory("edgeproc-conformance", IndexConfig(dimension=len(_VECTOR)))
    await index.insert(_rows(_MINE, _MINE_ROWS, key))
    await index.insert(_rows(_THEIRS, _THEIRS_ROWS, key))
    return index


async def _live_ids(index: VectorIndex, filters: Metadata | None = None) -> set[str]:
    """Every entity id a read can still reach."""
    return {entity_id for entity_id, _ in await index.search(_VECTOR, k=_K, filters=filters)}


async def _check_rows_are_readable_back(factory: IndexFactory, key: str) -> str | None:
    """Guard the guard: every check below reads state back through an unscoped search."""
    live = await _live_ids(await _seeded(factory, key))
    if live == _ALL_IDS:
        return None
    return (
        f"an unscoped search() returned {sorted(live)}, but insert() was just given "
        f"{sorted(_ALL_IDS)}. Every check below observes the index this way, so a pass "
        f"anywhere else would prove nothing until insert()/search() round-trip."
    )


async def _check_search_applies_filters(factory: IndexFactory, key: str) -> str | None:
    """The read-side promise the write side has to mirror."""
    mine = await _live_ids(await _seeded(factory, key), {key: _MINE})
    if mine == _ids(_MINE, _MINE_ROWS):
        return None
    return (
        f"search(filters={{{key!r}: {_MINE!r}}}) returned {sorted(mine)}, expected "
        f"{sorted(_ids(_MINE, _MINE_ROWS))}. A scoped read must return that scope's rows "
        f"and nobody else's — it is the promise delete() and get_stats() mirror."
    )


async def _check_search_ands_multi_key_filters(factory: IndexFactory, key: str) -> str | None:
    """Multiple filter keys are ANDed. One key cannot show that; two can."""
    matched = await _live_ids(await _seeded(factory, key), _and_filter(key))
    if matched == _AND_MATCHES:
        return None
    return (
        f"search(filters={_and_filter(key)}) returned {sorted(matched)}, expected "
        f"{sorted(_AND_MATCHES)}. Every filter key must match for a row to be returned. "
        f"Returning more means the keys were ORed, which widens a partition scope into "
        f"its neighbours; returning fewer means a legitimate multi-key scope sees nothing."
    )


async def _check_empty_filters_search_is_unscoped(factory: IndexFactory, key: str) -> str | None:
    """An empty mapping is no scope — and it is the shape IndexManager actually sends."""
    live = await _live_ids(await _seeded(factory, key), _UNSCOPED)
    if live == _ALL_IDS:
        return None
    return (
        f"search(filters={{}}) returned {sorted(live)}, expected {sorted(_ALL_IDS)}. An "
        f"empty filter mapping carries no scope, exactly like passing none — and it is "
        f"what IndexManager composes for every unscoped call, so reading it as a scope "
        f"that matches nothing blinds the library's own administrative reads."
    )


async def _check_scoped_delete_spares_other_partitions(
    factory: IndexFactory, key: str
) -> str | None:
    """The 0.3.0 hole itself: a scoped delete that ignores ``filters`` erases a neighbour."""
    index = await _seeded(factory, key)
    await index.delete(sorted(_ids(_THEIRS, _THEIRS_ROWS)), filters={key: _MINE})
    survivors = await _live_ids(index)
    if survivors == _ALL_IDS:
        return None
    return (
        f"delete(<ids owned by {_THEIRS}>, filters={{{key!r}: {_MINE!r}}}) destroyed "
        f"{sorted(_ALL_IDS - survivors)}. Those rows do not match the filter, so a scoped "
        f"delete may not touch them. This is cross-partition data destruction: the backend "
        f"is accepting `filters` and not applying it."
    )


async def _check_scoped_delete_removes_its_own_rows(factory: IndexFactory, key: str) -> str | None:
    """Non-vacuity for the check above: scoping a delete must not disarm it."""
    index = await _seeded(factory, key)
    doomed = f"{_MINE}-0"
    await index.delete([doomed], filters={key: _MINE})
    survivors = await _live_ids(index)
    if survivors == _ALL_IDS - {doomed}:
        return None
    return (
        f"delete([{doomed!r}], filters={{{key!r}: {_MINE!r}}}) left {sorted(survivors)}, "
        f"expected {sorted(_ALL_IDS - {doomed})}. That row matches the filter, so it has to "
        f"go — a backend that refuses every scoped delete is not isolating, it is broken."
    )


async def _check_unscoped_delete_is_administrative(factory: IndexFactory, key: str) -> str | None:
    """The documented boundary: absent filters means no scope, across every partition."""
    index = await _seeded(factory, key)
    doomed = [f"{_MINE}-0", f"{_THEIRS}-0"]
    await index.delete(doomed)
    survivors = await _live_ids(index)
    if survivors == _ALL_IDS - set(doomed):
        return None
    return (
        f"delete({doomed}) with no filters left {sorted(survivors)}, expected "
        f"{sorted(_ALL_IDS - set(doomed))}. An unscoped delete is an administrative, "
        f"cross-partition write — the library never guesses a scope the caller did not supply."
    )


async def _check_multi_key_delete_ands_its_filters(factory: IndexFactory, key: str) -> str | None:
    """The AND rule on the destructive path: ORing here erases a neighbour's rows."""
    index = await _seeded(factory, key)
    await index.delete(sorted(_ALL_IDS), filters=_and_filter(key))
    survivors = await _live_ids(index)
    if survivors == _ALL_IDS - _AND_MATCHES:
        return None
    return (
        f"delete(<every seeded id>, filters={_and_filter(key)}) left {sorted(survivors)}, "
        f"expected {sorted(_ALL_IDS - _AND_MATCHES)}. Only {sorted(_AND_MATCHES)} matches "
        f"both keys. Destroying more means the keys were ORed — a scoped delete reaching "
        f"rows a scoped read could not see; destroying fewer means it reached none."
    )


async def _check_empty_filters_delete_is_administrative(
    factory: IndexFactory, key: str
) -> str | None:
    """``delete(ids, filters={})`` is the unscoped delete, not a delete of nothing."""
    index = await _seeded(factory, key)
    doomed = [f"{_MINE}-0", f"{_THEIRS}-0"]
    await index.delete(doomed, filters=_UNSCOPED)
    survivors = await _live_ids(index)
    if survivors == _ALL_IDS - set(doomed):
        return None
    return (
        f"delete({doomed}, filters={{}}) left {sorted(survivors)}, expected "
        f"{sorted(_ALL_IDS - set(doomed))}. An empty mapping is the *absence* of a scope, "
        f"so this is the administrative cross-partition delete — and it is the only shape "
        f"IndexManager ever composes for one. Read as a scope, it deletes nothing and says so."
    )


async def _check_unscoped_stats_report_the_physical_total(
    factory: IndexFactory, key: str
) -> str | None:
    """Non-vacuity for the scoped count: the collision has to be real before it can be filtered."""
    physical = (await (await _seeded(factory, key)).get_stats()).vector_count
    if physical == _TOTAL_ROWS:
        return None
    return (
        f"an unscoped get_stats() reported vector_count={physical}, expected {_TOTAL_ROWS} "
        f"— the index holds {_MINE_ROWS} + {_THEIRS_ROWS} rows. Absent filters means the "
        f"physical index's own totals, and a scoped count cannot be graded until this is right."
    )


async def _check_scoped_stats_count_only_their_partition(
    factory: IndexFactory, key: str
) -> str | None:
    """The other half of the 0.3.0 hole: scoped stats that report the physical total."""
    scoped = (await (await _seeded(factory, key)).get_stats(filters={key: _MINE})).vector_count
    if scoped == _MINE_ROWS:
        return None
    return (
        f"get_stats(filters={{{key!r}: {_MINE!r}}}) reported vector_count={scoped}, expected "
        f"{_MINE_ROWS}. The other {_THEIRS_ROWS} rows in this index belong to {_THEIRS!r}; "
        f"reporting a partition on a neighbour's rows leaks their row count to whoever asks."
    )


async def _check_empty_filters_stats_report_the_physical_total(
    factory: IndexFactory, key: str
) -> str | None:
    """``get_stats(filters={})`` is the physical total, not the count of an empty scope."""
    physical = (await (await _seeded(factory, key)).get_stats(filters=_UNSCOPED)).vector_count
    if physical == _TOTAL_ROWS:
        return None
    return (
        f"get_stats(filters={{}}) reported vector_count={physical}, expected {_TOTAL_ROWS}. "
        f"An empty mapping is no scope, so this is the physical index's own total — the "
        f"same answer passing no filters gives, and the only shape IndexManager composes "
        f"when a caller asks for stats without a partition key."
    )


async def _check_multi_key_stats_count_the_intersection(
    factory: IndexFactory, key: str
) -> str | None:
    """The AND rule on the reporting path: ORing here inflates a count with a neighbour's rows."""
    scoped = (await (await _seeded(factory, key)).get_stats(filters=_and_filter(key))).vector_count
    if scoped == len(_AND_MATCHES):
        return None
    return (
        f"get_stats(filters={_and_filter(key)}) reported vector_count={scoped}, expected "
        f"{len(_AND_MATCHES)}. Only rows matching *every* key count. Counting more means "
        f"the keys were ORed, which reports a neighbour's rows as this scope's; counting "
        f"fewer means a multi-key scope cannot see its own."
    )


_Check = Callable[[IndexFactory, str], Awaitable[str | None]]

_CHECKS: Final[tuple[_Check, ...]] = (
    _check_rows_are_readable_back,
    _check_search_applies_filters,
    _check_search_ands_multi_key_filters,
    _check_empty_filters_search_is_unscoped,
    _check_scoped_delete_spares_other_partitions,
    _check_scoped_delete_removes_its_own_rows,
    _check_multi_key_delete_ands_its_filters,
    _check_unscoped_delete_is_administrative,
    _check_empty_filters_delete_is_administrative,
    _check_unscoped_stats_report_the_physical_total,
    _check_empty_filters_stats_report_the_physical_total,
    _check_scoped_stats_count_only_their_partition,
    _check_multi_key_stats_count_the_intersection,
)


async def _failures(factory: IndexFactory, key: str) -> list[str]:
    """Every conformance property this backend breaks, named and explained, in check order."""
    found: list[str] = []
    for check in _CHECKS:
        problem = await check(factory, key)
        if problem is not None:
            found.append(f"{check.__name__.removeprefix('_check_')}: {problem}")
    return found


def _report(failures: list[str]) -> str:
    """One message naming every broken property — an implementer's whole punch list."""
    numbered = "\n\n".join(f"{n}. {text}" for n, text in enumerate(failures, start=1))
    return (
        f"{len(failures)} of {len(_CHECKS)} VectorIndex conformance checks failed.\n\n"
        f"{numbered}\n\n"
        f"See the edgeproc-core CHANGELOG for 0.3.0: delete() and get_stats() must accept "
        f"*and apply* `filters`. Accepting the argument and ignoring it still type-checks, "
        f"still passes a backend's own suite, and silently destroys other partitions' rows."
    )


def _reject_reserved_key(partition_key_name: str) -> None:
    """Refuse to run when the caller's key collides with the suite's second dimension."""
    if partition_key_name != _TIER_KEY:
        return
    raise ValueError(
        f"partition_key_name may not be {_TIER_KEY!r}: the suite seeds that key itself as "
        f"the second dimension its multi-key checks filter on, and one would overwrite the "
        f"other — collapsing every AND-vs-OR check back into a single-key one that cannot "
        f"fail. Pass any other key; no check depends on how yours is spelled."
    )


async def assert_vector_index_conformance(
    factory: IndexFactory,
    partition_key_name: str = "tenant_id",
) -> None:
    """Assert ``factory``'s indices honour the ``VectorIndex`` filtering contract.

    Args:
        factory: How to build a fresh index — the same async
            ``(name, config) -> VectorIndex`` callable you hand a partition
            strategy. Each check builds its own index through it.
        partition_key_name: The metadata key the suite partitions on. Defaults to
            ``"tenant_id"``, matching ``IndexManager``'s default; pass your own
            (``"org_id"``, ``"user_id"``, …) if that is what your backend indexes.
            May not be ``"conformance_tier"`` — the suite seeds that key itself.

    Raises:
        AssertionError: If any check fails. The message names every broken
            property and says what was expected versus what happened.
        ValueError: If ``partition_key_name`` is the suite's own reserved key, which
            would silently disarm the multi-key checks rather than fail them.
    """
    _reject_reserved_key(partition_key_name)
    failures = await _failures(factory, partition_key_name)
    if failures:
        raise AssertionError(_report(failures))
