# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies
uv sync

# THE canonical gate — run before every commit; mirrors CI exactly
uv run poe gate

# Run all tests (includes coverage, requires 90%+)
uv run pytest

# Run specific test file
uv run pytest tests/test_types.py

# Run specific test method
uv run pytest tests/test_index_manager.py::TestIndexManager::test_insert

# Individual gate steps
uv run poe lint         # ruff check
uv run poe fmt-check    # ruff format --check
uv run poe typecheck    # mypy --strict
uv run poe complexity   # xenon A/A/A
uv run poe test         # pytest

# Auto-fix
uv run poe fmt
uv run ruff check --fix .
```

## Quality Gates (Non-Negotiable)

`uv run poe gate` must be green before any commit lands on `main`. It runs, in
order: ruff lint → `ruff format --check` → `mypy --strict` → xenon A/A/A →
pytest (≥90% coverage, writes `coverage.xml`).

Scars — the real bug behind each rule:

- **The gate mirrors `ci.yml` exactly, both directions.** Until 2026-07-11 the
  local task (`poe quality`) omitted `ruff format --check` while CI ran it, and
  CI omitted the xenon complexity step while the local task ran it — each side
  could be green while the other failed. Any step added to one MUST land in the
  other in the same commit.
- **`poe gate` is the only name; no aliases.** This repo called it `poe
  quality` while sibling repos said `poe gate`; per-repo trivia is how gate
  steps get silently skipped.
- **A red scheduled workflow is a red repo.** The weekly `security-audit.yml`
  (pip-audit) doesn't block merges, so check it explicitly with `gh run list`.
  Its very first run caught two real CVEs (pygments, pytest) sitting behind a
  green CI badge.

## WASM / edge-compute declaration

House standard §8: **not applicable.** This is a pure-Python protocol library —
it ships no WASM, browser, or edge runtime. (Downstream projects implement
those patterns on top of this library's protocols.)

## Architecture Overview

This library provides vector partitioning (insert routing + top-k result merging) with flexible partitioning strategies. It ships the partitioning protocol and an in-memory brute-force reference index — **not** an HNSW implementation; the HNSW `m` / `ef_construction` values in `IndexConfig` are pass-through knobs carried to whatever backend implements `VectorIndex`. Core principle: do NOT create one index per tenant—use global or bucketed indices with metadata filtering.

The architecture diagram lives inline in [`README.md`](README.md) as a mermaid block —
GitHub renders it natively, so there is no `.svg` build artifact to regenerate or let go
stale. Deep-dive diagrams are inline in
[`docs/vector-mgmt-architecture.md`](docs/vector-mgmt-architecture.md).

### Public API

```python
from edgeproc_core import (
    IndexManager,
    PartitionStrategy, GlobalPartitionStrategy, BucketedPartitionStrategy, TwoTierPartitionStrategy,
    IndexConfig, IndexStats, VectorEmbedding, VectorIndex,
)
```

### Core Types (`vector_mgmt/core/types.py`)

**VectorEmbedding**: Pydantic model for vectors.
- `entity_id`, `embedding: list[float]`, `metadata: dict[str, Scalar]`
  (`Scalar = str | int | float | bool | None` — no `Any`).
- `tenant_id`: Deprecated—use `metadata["tenant_id"]` instead
- `get_partition_key(key_name)`: Resolves from metadata, falls back to `tenant_id`

**IndexConfig**: index tuning knobs. `m` / `ef_construction` are HNSW *pass-through* parameters — carried to a downstream backend, not used to build an HNSW graph in this library.
- `m=32`: Graph connectivity (higher = better recall, more memory)
- `ef_construction=200`: Build-time search depth
- `ef_search=100`: Query-time search depth
- `dimension=1536`, `distance_metric="cosine"`

**IndexStats**: Index health metrics. Key fields: `tombstone_percentage`, `index_size_mb`.

**VectorIndex Protocol**: Interface for vector DB implementations.
- `insert(embeddings)`, `delete(entity_ids)`, `rebuild(config)`
- `search(query_vector, k, filters, ef_search)` → `list[(entity_id, distance)]` (lower distance = more similar)
- `get_stats()` → `IndexStats`

### IndexManager (`vector_mgmt/core/index_manager.py`)

Orchestrates vector operations: `insert()`, `search()`, `delete()`, `get_stats()`, `rebuild_if_needed()`.

`rebuild_if_needed()` auto-triggers when: tombstone_percentage > 10% OR index_size_mb > 1000.

### Partitioning Strategies (`vector_mgmt/partitioning/strategies.py`)

All inherit from `PartitionStrategy` ABC with `partition_key_name` and `partition_key_extractor` options.

| Strategy | Scale | Behavior |
|----------|-------|----------|
| GlobalPartitionStrategy | <50K keys | Single index, metadata filtering |
| BucketedPartitionStrategy | 50K-5M keys | Hash routing to N buckets (default 256) |
| TwoTierPartitionStrategy | Time-based | Hot/cold split on `created_at` metadata |

Bucket collisions are expected by design (keys outnumber buckets). Isolation
comes from the partition-key filter applied inside the index, not from disjoint
buckets — `tests/test_tenant_isolation.py` forces `num_buckets=1` and proves a
scoped read still returns only its own rows. Never treat a partition name as a
security principal.

### Canonical Errors (`errors/`)

A second, independent module — unrelated to vector search, and roughly 44% of
production code. The Python mirror of the TS `@edgeproc/errors` package, so a
failure keeps one stable identity on both sides of the portfolio.

```python
from edgeproc_core.errors import define_errors, starter_pack

registry = define_errors(starter_pack)        # 18 universal codes; or declare your own
registry.classify({"status": 402})            # raw failure -> 'ai.provider.out_of_credits'
registry.describe(code, params, t)            # code -> human text, via your i18n
registry.to_problem_details(code).to_dict()   # -> RFC 9457 wire object
```

- `types.py` — `Category`, `CatalogEntry`, `ProblemDetails`, type aliases.
- `registry.py` — `Registry` + `define_errors`; duplicate codes rejected at registration.
- `starter_pack.py` — the 18 universal provider/config/network/timeout/device/integrity/internal codes.
- `raw.py` — duck-typing helpers (`http_status_of`, `error_name_of`, `error_text_of`) for custom `match` rules.

Runnable demo: `examples/canonical_errors.py`.

### Key Design Pattern: Index Factory

```python
async def factory(name: str, config: IndexConfig) -> VectorIndex:
    return YourVectorIndexImpl(name, config)

strategy = GlobalPartitionStrategy(index_factory=factory, ...)
```

### Reference In-Memory Index (`vector_mgmt/testing.py`)

`InMemoryVectorIndex` is a conformant, *non-production* `VectorIndex` implementation.
Use it in tests and in the bundled `examples/`. Production code should implement
the protocol against a real backend (see `edge-proc`'s `LocalVecIndex` for a
FAISS-backed reference).

`in_memory_factory(name, config)` is the matching `IndexFactory` callable.

## Testing

Tests use `InMemoryVectorIndex` from `edgeproc_core.vector_mgmt.testing` —
the same reference implementation the examples consume.

The legacy `MockVectorIndex` in `tests/conftest.py` is retained only for the
existing strategy tests that depend on its quirks.

## Examples

See `examples/` for runnable usage patterns. `bash examples/run_loop.sh` walks
all three examples end-to-end against the bundled in-memory factory.

## Dependencies

Core: `pydantic>=2.5`. The `pgvector`, `sqlalchemy[asyncio]`, and `numpy`
extras are opt-in via the `pgvector` optional-dependency group.

## Code Style

- Line length: 100 chars
- Python 3.13+ type hints (`list[T]` not `List[T]`)
- Google-style docstrings
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`

## Reference Docs

- `docs/vector-mgmt-architecture.md`: Deep dive on partitioning rationale and scaling guidelines (note: some sections describe planned features)
