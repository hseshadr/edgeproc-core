# edgeproc-core

[![CI](https://github.com/hseshadr/edgeproc-core/actions/workflows/ci.yml/badge.svg)](https://github.com/hseshadr/edgeproc-core/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/hseshadr/edgeproc-core/branch/main/graph/badge.svg)](https://codecov.io/gh/hseshadr/edgeproc-core)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI models turn text, images, and products into **embeddings** — long lists of
numbers where similar things get similar numbers. Finding the embeddings closest
to a query is called **vector search**, and it is how "more like this" features
work.

This library answers one specific, deceptively hard question about vector
search: when your data belongs to many different owners — users, tenants, time
periods — **how do you split it up so search stays fast and nobody ever sees
anyone else's results?** You bring the search index (FAISS, pgvector, hnswlib,
…); this library routes every vector into the right partition and merges
search results back out. Swapping partitioning schemes is a one-line change,
and the index backend never has to know.

It is the bottom, most generic layer of a three-repo MIT-licensed stack — the
partitioning *protocol* (a *protocol* here is just the set of methods a search
backend must provide — Python's `typing.Protocol`, nothing to subclass),
nothing more:

```
edge-reco        hybrid search + recommendations, running in the browser
  └─ edge-proc   ships big files to devices and proves they arrived unmodified
       └─ edgeproc-core   ← you are here: the vector-partitioning protocol
```

**Status:** v0.2.1, alpha. Small and focused by design — the foundation, not
the headline. The hosted CI run and the full local gate pass at **98.41%
coverage measured with branches enabled**, with strict mypy, lint, and
formatting. The gate runs `--cov-branch` and enforces a ≥90% branch coverage
floor, so that is a measurement and not an assertion. Split into its two parts:
98.62% of statements and 97.54% of branches are covered. A gate step re-derives
all three figures from `coverage.xml` on every run, so this paragraph cannot
quietly drift away from what the suite actually measures.

As of `v0.2.1` the package is published on
[PyPI](https://pypi.org/project/edgeproc-core/), so `pip install edgeproc-core`
is the supported install. See [Installation](#installation).

The bundled benchmark (`benchmarks/benchmark.py`) reports
**routing p50 5.8 ms / p95 6.0 ms** for 10,000 embeddings across 256 buckets,
and **reference search p50 19.0 ms / p95 19.2 ms** against the bundled
in-memory index — see [`InMemoryVectorIndex`](#60-second-quickstart) below for
what that reference index is (and isn't).

Measured 2026-07-20 on an Apple M3 Pro (macOS 26.5, arm64, CPython 3.13.5),
20 samples per run, machine otherwise idle. Across six consecutive runs routing
p50 spanned 5.7–6.1 ms and search p95 spanned 18.7–20.2 ms; a busy machine
measures materially higher. These describe that tree on that laptop, not a
promise for your hardware — reproduce with:

```bash
uv run python benchmarks/benchmark.py
```

```bash
uv sync
uv run poe gate
```

This repository is a protocol and reference implementation, not a hosted search
service. The caller owns backend isolation, resource ceilings, and production SLOs;
`edge-proc` supplies the local runtime that consumes these contracts.

## 60-second quickstart

A teaser against the bundled in-memory reference index — produces real output.

```python
import asyncio
from edgeproc_core import GlobalPartitionStrategy, IndexManager
from edgeproc_core.vector_mgmt.core.types import VectorEmbedding
from edgeproc_core.vector_mgmt.testing import in_memory_factory

async def demo() -> None:
    strategy = GlobalPartitionStrategy(index_factory=in_memory_factory)
    manager = IndexManager(partition_strategy=strategy)
    await manager.insert(
        [VectorEmbedding(entity_id="a", embedding=[0.1, 0.2, 0.3, 0.4], tenant_id="t1")],
        partition_key="t1",
    )
    print(await manager.search([0.1, 0.2, 0.3, 0.4], k=5, partition_key="t1"))

asyncio.run(demo())  # → [('a', ~0.0)]  exact match, cosine distance ≈ 0
```

Or run all five bundled examples end-to-end:

```bash
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core
uv sync
bash examples/run_loop.sh
```

`InMemoryVectorIndex` is a reference implementation for tests and examples; in
production you implement `VectorIndex` against your own backend. See
[`edge-proc`'s `LocalVecIndex`](https://github.com/hseshadr/edge-proc) for a
FAISS-backed example.

## Installation

Requires **Python 3.13 or newer**.

Install from [PyPI](https://pypi.org/project/edgeproc-core/):

```bash
uv pip install edgeproc-core
```

In your `pyproject.toml`:
```toml
dependencies = [
  "edgeproc-core>=0.2.1",
]
```

Verify it worked:
```bash
python -c "import edgeproc_core; print(edgeproc_core.__version__)"
# 0.2.1
```

Prefer to build from source? Pin a full commit SHA — Git cannot repoint it, so
it is exactly as immutable as a release:

```bash
uv pip install "edgeproc-core @ git+https://github.com/hseshadr/edgeproc-core.git@6cdf8475b223262821622a021c561aed9213a472"
```

> **Why do source pins use a commit and not a tag?** Tags `v0.2.0` and older
> were cut before the import package was renamed to `edgeproc_core`, so they
> ship the old `shared_libs_python` module and every example here would raise
> `ModuleNotFoundError`. Pin a commit at or after the rename (like the one
> above), or install `v0.2.1`+ from PyPI as shown first.

For local development:
```bash
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core
uv sync
```

## Under the hood (for developers)

- **Two Protocols decouple everything.** The partitioning strategy is separated
  from the index backend behind `VectorIndex` and `IndexFactory`. Swap the
  strategy (`Global` / `Bucketed` / `TwoTier`) without touching the index; swap
  the index without touching the strategy.
- **Why it exists.** Every multi-tenant vector-search system rediscovers the
  same partitioning patterns ("global + filter", "hash buckets", "hot/cold").
  This library does that once, cleanly typed, so downstream projects
  (`edge-proc`, …) can `import edgeproc_core` instead of reinventing it.
- **Quality bar.** `mypy --strict` clean, xenon Grade A complexity, ≥90% branch
  coverage. Backwards-compatible with the legacy `tenant_id` API.

[`edge-proc`](https://github.com/hseshadr/edge-proc) implements this library's
`VectorIndex` protocol over FAISS, and [`edge-reco`](https://github.com/hseshadr/edge-reco)
([live demo](https://edge-reco.com)) is built on `edge-proc`. A clean partitioning
protocol is what lets the vector index ship as a content-addressed, CDN-distributable,
locally-runnable artifact — the foundation of zero-per-query-cost, offline-capable
search.

### Source tree

```
edgeproc_core/
  vector_mgmt/
    core/
      types.py          # VectorEmbedding, IndexConfig, IndexStats, VectorIndex, IndexFactory
      index_manager.py  # IndexManager — routes inserts, merges top-k searches
    partitioning/
      strategies.py     # GlobalPartitionStrategy, BucketedPartitionStrategy, TwoTierPartitionStrategy
    testing.py          # InMemoryVectorIndex — reference impl for tests + examples
  errors/               # canonical error codes (see "Canonical errors" below)
    types.py            # Category, CatalogEntry, ProblemDetails (RFC 9457)
    registry.py         # Registry + define_errors — classify / describe / serialize
    starter_pack.py     # 18 universal codes, ready to reuse
    raw.py              # duck-typing helpers for failures of unknown shape
    canonical_error.py  # CanonicalError, DuplicateCodeError
examples/               # basic / custom-key / composite-key / two-tier / errors, plus run_loop.sh
tests/                  # pytest suite (≥90% branch coverage enforced by the gate)
```

### Partitioning strategies

All strategies accept `partition_key_name` (default `"tenant_id"`) and an
optional `partition_key_extractor` callable.

| Strategy | When to use | How it routes |
|----------|-------------|---------------|
| `GlobalPartitionStrategy` | < 50K partition keys | One global index; filter by metadata at query time — [example](examples/basic_usage.py) |
| `BucketedPartitionStrategy` | 50K – 5M partition keys | Hash the partition key into one of N buckets (default 256) — [example](examples/custom_partition_key.py) |
| `TwoTierPartitionStrategy` | Time-keyed workloads | Split by `metadata["created_at"]` into a hot tier and a cold tier — [example](examples/two_tier_partition.py) |

Bucketing means collisions are expected by design: once partition keys outnumber
buckets, two tenants share one physical index. Isolation does not depend on them
landing in different buckets — a scoped read filters by partition key inside the
index. [`tests/test_tenant_isolation.py`](tests/test_tenant_isolation.py) proves
this by forcing the worst case (`num_buckets=1`, every key colliding) and
asserting a tenant still sees only its own rows. Partition names are routing
hints, never security principals: enforce isolation in your backing store too.

The deep dive (rationale, scaling math, recommended `m` / `ef_construction`)
lives in [`docs/vector-mgmt-architecture.md`](docs/vector-mgmt-architecture.md).
The security, privacy, reliability, and measured-performance ownership contract
lives in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

### Canonical errors

The package ships a second, independent module: `edgeproc_core.errors`.
It has nothing to do with vector search — it solves a different recurring
problem, and it is roughly as much code as the partitioning layer.

**The problem.** The same failure arrives in a dozen shapes. An HTTP 402, a
thrown `TimeoutError`, a browser's "Failed to fetch" — each is a different
object, so every layer of an app re-writes the same brittle `if` ladder to
decide what to show the user, and the answers drift apart.

**What it does.** You register a *catalog* — a set of stable, namespaced codes
like `net.unreachable` — and then always speak in codes:

- `classify(raw)` turns any raw failure into a stable code
- `describe(code)` renders human text, through your own i18n if you have one
- `to_problem_details(code).to_dict()` produces the [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)
  Problem Details JSON an API returns

```python
from edgeproc_core.errors import define_errors, starter_pack

registry = define_errors(starter_pack)          # 18 universal codes, or bring your own
registry.classify({"status": 402})              # → 'ai.provider.out_of_credits'
registry.describe("net.unreachable")            # → "Couldn't reach the server. …"
registry.to_problem_details("net.unreachable").to_dict()
```

`starter_pack` covers the common provider / config / network / timeout / device
/ integrity / internal cases so you need not re-declare them; `define_errors`
rejects a duplicate code at registration. The codes match the TypeScript
`@edgeproc/errors` package, so a failure keeps one identity across a stack.

Runnable demo: [`examples/canonical_errors.py`](examples/canonical_errors.py).

### Generic partition keys

The library was originally `tenant_id`-only. v0.1+ supports any partition key:

- store it in `VectorEmbedding.metadata` (e.g. `{"user_id": "u1"}`),
- pass `partition_key_name="user_id"` to your strategy and manager,
- optionally pass a `partition_key_extractor` for composite keys (see
  [`examples/composite_partition_key.py`](examples/composite_partition_key.py)).

The legacy `tenant_id` field on `VectorEmbedding` still works.

### Development

```bash
uv sync
uv run poe gate         # THE gate: lint + format check + mypy --strict + xenon A + tests ≥90% cov
uv run poe lint
uv run poe fmt          # auto-format
uv run poe fmt-check    # format check only (part of the gate)
uv run poe typecheck    # mypy --strict
uv run poe complexity   # xenon Grade A (cyclomatic ≤ 5)
uv run poe test
```

`uv run poe gate` mirrors CI exactly, both directions — if it passes locally,
CI passes. The whole public surface — not just edited code — must clear it
before a release tag is cut.

## License

MIT.
