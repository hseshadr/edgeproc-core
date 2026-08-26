# Security, privacy, reliability, and performance contract

**TL;DR.** `edgeproc-core` is an in-process routing protocol, not a hosted
vector database. It performs no network or filesystem I/O and emits no telemetry.
It deterministically chooses partitions and delegates storage, authorization,
timeouts, durability, and query execution to the caller-provided `VectorIndex`.
This page states that ownership boundary so downstream products do not mistake a
typed partition key for an access-control system or an example index for a service SLA.

## Threat model and trust boundaries

| Boundary | This library guarantees | The consumer must guarantee |
| --- | --- | --- |
| Partition selection | Stable SHA-256 bucketing; positive bucket count; concurrency-safe lazy index creation | Derive keys from authenticated identity; never trust a request payload as authorization |
| Backend protocol | Strict typed calls; backend exceptions propagate instead of becoming empty results | Authentication, row-level security, filter parameterization, encryption, credentials, rate limits, and query deadlines |
| Result merge | Deterministic distance ordering and duplicate-ID collapse | Distances from different partitions use compatible metrics and calibration |
| Reference index | Correct brute-force cosine behavior for tests/examples | Do not expose it as a production multi-tenant index or durability layer |

Partition names are routing hints, not security principals. Bucket collisions are
expected, so isolation must be enforced again in the backing database. A compromised
process can read every in-memory object; this package does not claim protection from
the host application or interpreter.

## Privacy and data flow

`VectorEmbedding` values, metadata, tenant/partition keys, filters, and query vectors
move only from caller memory into the supplied `VectorIndex`. The shipped package has
no HTTP client, file writer, logger, analytics SDK, prompt path, background thread, or
cloud fallback. It neither redacts nor serializes caller data.

The bundled `InMemoryVectorIndex` retains live embeddings until `delete`, process exit,
or object disposal. Deletion tombstones an ID so a stale reinsert cannot resurrect it;
`rebuild` clears tombstone bookkeeping after live data is already gone. A production
backend owns retention, backup, restore, legal hold, deletion proof, and log scrubbing.

## Reliability and recovery contract

- Invalid bucket counts fail at construction; unknown two-tier partitions fail loudly.
- Lazy factories are protected by an `asyncio.Lock`, so concurrent first use creates
  one index per partition.
- Backend failures and cancellations propagate. The library performs no silent retry,
  fallback, or conversion to an empty result.
- Multi-partition work is sequential but not transactional. If a later backend call
  fails, earlier partitions may already have changed; consumers needing atomicity must
  provide a transactional backend or an idempotent operation/reconciliation layer.
- The library sets no universal service timeout. Wrap backend calls in a product-owned
  deadline such as `asyncio.timeout(...)` and publish recovery objectives at that layer.
- `rebuild_if_needed` performs at most one rebuild per call, keeping maintenance work
  bounded and observable to the caller.

There is no hosted availability SLA. Security reports are acknowledged within 48 hours
and receive an initial assessment within seven days, as stated in `SECURITY.md`.

## Measured performance contract

Budgets cover only code this repository owns. They are deliberately generous across
developer and CI machines and must be measured before a release:

| Workload | Budget |
| --- | ---: |
| Route 10,000 eight-dimensional embeddings into 256 buckets | p50 <= 100 ms; p95 <= 200 ms |
| In-memory reference exact top-10 over 10,000 x 32 floats | p50 <= 500 ms; p95 <= 750 ms |

Local release measurement on 2026-07-20 (Apple M3 Pro, macOS 26.5 arm64, CPython
3.13.5, 20 samples per run, machine otherwise idle):
**routing p50 5.8 ms / p95 6.0 ms**; **reference search p50 19.0 ms / p95 19.2 ms**.
Across six consecutive runs routing p50 spanned 5.7–6.1 ms and search p95 spanned
18.7–20.2 ms, so read any single figure as a representative sample, not a floor —
a loaded machine measures materially higher.
Treat the checked-in budgets—not one developer machine's faster result—as the contract.

Run the repeatable 20-sample benchmark:

```bash
uv run python benchmarks/benchmark.py
```

The second row is an examples/testing guard, not a production promise. Backend query
latency, recall, concurrency, memory, p99 tails, and availability belong to the selected
FAISS/pgvector/HNSW implementation and the product that operates it. The deeper
architecture guide labels those values as consumer targets rather than shipped claims.

## Release proof

A release requires a fresh manual `workflow_dispatch`; pushing a tag never publishes by
itself. Dagger first requires that the requested commit is the exact current `main` commit
with a green hosted `Dagger` check. It fetches that immutable commit itself and verifies
exact tag, package-version, and top-changelog identity. Dagger then runs the full gate, the
real example, the benchmark, the locked dependency audit, and secret scans over both the
exact snapshot and full Git history. It builds the wheel and sdist without build isolation,
validates their project and version metadata, and records their literal SHA-256 identities.

Dagger builds and validates in an unprivileged job and exports one exact, short-lived
candidate. A pinned artifact-upload action is the only bridge out of that job. Its successful
manual run triggers `publish.yml` from protected default-branch code. That source-free
OIDC-bearing job only invokes pinned artifact download and the official PyPI publish action;
it has no checkout, shell, dependency install, build backend, or project code execution. The
manual dispatch is the fresh publication authorization.

Do not publish from local evidence alone, and do not call a consumer backend healthy from
this protocol's tests. Record the immutable commit/tag and benchmark JSON for the release.
