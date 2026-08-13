# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.2] — 2026-08-13

This corrective patch supersedes 0.4.1's immutable installation guidance. The runtime
code is unchanged; the release repairs what source code those instructions select and
makes that safety property part of the gate.

### Fixed
- **The documented immutable source pin now selects the supported 0.4.x line.** The old
  commit still imported successfully but predated the scoped partition-isolation fixes.
  Every README and installation-guide source command now uses the protected-main 0.4.2
  preparation commit, while PyPI examples name 0.4.2. `SECURITY.md` marks earlier
  versions superseded.
- **The release description no longer snapshots which version PyPI served while the
  release was being prepared.** It identifies the version packaged with the README, so
  the immutable PyPI description cannot become stale immediately after publication.

### Added
- **Source-pin verification now checks behavior, not package shape.** The gate materializes
  every documented immutable ref, builds and installs it into an isolated target, proves
  it belongs to the current supported minor line, forces two scopes into one physical
  bucket, and verifies scoped search, stats, and deletion keep the neighbouring scope
  intact. An import-only check can no longer certify an unsafe historical snapshot.

## [0.4.1] — 2026-08-12

This patch release makes the strengthened backend-isolation conformance contract
installable. It also gives successful PyPI uploads a measured ten-minute propagation
window before declaring the release missing.

### Changed
- **The secret scan is now one shared brick, not an inlined copy.** `ci.yml` called
  `gitleaks/gitleaks-action` directly; it now calls
  `hseshadr/ci/.github/workflows/secret-scan.yml`, pinned to the commit SHA behind
  `ci-v3.2.1`. The shared copy is stricter than the one it replaces: it checks out with
  `persist-credentials: false` and grants `pull-requests: read`, and the inlined job had
  neither. The reported check name changes from `gitleaks` to `Secret scan / gitleaks`,
  so `main`'s required-status list has to move with it.
- **Corrected a false claim about what the secret scan covers.** The old job was labelled
  a "full-history" scan. It was not one, and neither is this one. On `push` and
  `pull_request`, gitleaks-action runs with
  `--log-opts=--no-merges --first-parent <base>^..<head>`, so it reads only the commits
  that push or PR introduces; `fetch-depth: 0` merely makes the base commit reachable so
  the range resolves. A genuine full sweep happens only on a `schedule` or
  `workflow_dispatch` event, where the action omits `--log-opts` entirely — and `ci.yml`
  fires on neither, so this repository's pre-existing history has never been scanned.

### Fixed
- **The conformance suite certified backends that leak.** `assert_vector_index_conformance`
  is the contract a storage backend must satisfy, and through 0.4.0 it could be passed by
  two implementations that break tenant isolation. Both holes are the same shape — a
  method never called with an argument shape the library itself produces — and both are
  now closed, taking the suite from 7 checks to 13.

  *Filter keys were never shown to be ANDed.* Every filter the suite passed carried
  exactly **one key**, and one key means the same thing under AND and under OR. The suite
  was therefore structurally incapable of telling them apart, and graded an ORing backend
  as conformant. This is not academic: `IndexManager._compose_filters` merges the
  partition scope *into* the caller's filters, so every scoped call carrying a filter of
  its own is a two-key filter — and under OR the partition key stops narrowing anything.
  A tenant-scoped `search` returns every other tenant's matching rows, and the matching
  `delete` destroys them. The suite now seeds a second metadata dimension
  (`conformance_tier`) and grades a two-key filter on `search`, `delete` and `get_stats`,
  failing a backend that matches too many rows *or* too few.

  *`filters={}` was never passed.* The suite called `delete(ids)` and
  `delete(ids, filters={key: value})`, never `delete(ids, filters={})` — which is the one
  shape that matters, because `_compose_filters(None, None)` returns `{}` and never
  `None`. An empty mapping is how **every** unscoped call the library makes actually
  reaches a backend. A backend reading it as "a scope no row satisfies" — the empty
  `IN ()` clause a SQL renderer produces by accident — silently no-ops every
  administrative delete, deletes nothing, raises nothing, and passed conformance. Graded
  now on all three methods.

  Both wrong backends are kept permanently in `tests/test_conformance_suite.py`
  (`_OrsMultiKeyFiltersIndex`, `_EmptyFiltersMatchNothingIndex`) and asserted to be
  rejected by name, alongside the fixtures that were already there. The shipped
  `InMemoryVectorIndex` needed no change: it was already correct on both properties, but
  nothing had ever proven it. `MockVectorIndex`, the backend `tests/test_index_manager.py`
  grades the manager's scoping against, is now run through the suite too — it was a second
  backend that had never been certified at all.

### Changed
- **`VectorIndex`'s docstrings now state the two rules the suite grades**, which were
  previously implied by `IndexManager`'s behaviour and written down nowhere: filter keys
  are ANDed, and an empty filter mapping is the absence of a scope rather than an empty
  one. A contract a backend author cannot read is a contract they will get wrong.
- `assert_vector_index_conformance` raises `ValueError` when `partition_key_name` is
  `"conformance_tier"`, the key the suite seeds as its own second dimension. Accepting it
  would overwrite the tier on every row and quietly collapse the multi-key checks back
  into single-key ones — reporting a pass on the exact property it could no longer see.
- **The publish workflow's registry check failed a release that had actually shipped.**
  `0.4.0` is live on PyPI, and
  [its publish run is red](https://github.com/hseshadr/edgeproc-core/actions/runs/30842985605)
  because the verification step gave PyPI only ~60s to start serving it. Measured
  propagation runs to ~120s for a normal PyPI release and ~200s for the first publish of a
  brand-new package name, so the bound was simply too tight. A red run on a live release is
  worse than noise — it teaches the reader to wave off red publish runs, which is how the
  six-green-runs-while-the-package-404'd defect comes back. The check is unchanged in
  design (ask the registry, never trust the uploader, a timeout is still a FAILURE); only
  its bound moves, to 14 attempts with backoff — 600s of sleep, 3x the slowest case
  measured — and its failure message now separates "still propagating" from "the release
  never happened". Text kept identical to `hseshadr/ci`'s `python-publish.yml`, which this
  job is an inline copy of.

## [0.4.0] — 2026-08-03

`conformance.py` merged 14 minutes after the `v0.3.0` tag was cut, so the published
0.3.0 wheel and sdist do not contain it while `README.md` tells implementers to
`from edgeproc_core.vector_mgmt.conformance import ...`. A clean-venv
`pip install edgeproc-core==0.3.0` followed by that import raises
`ModuleNotFoundError`. PyPI files are immutable, so 0.3.0 cannot be repaired —
this release is the first one that actually ships the module its docs describe.

It also carries a data-integrity fix (`insert` never stamped the routing key into
metadata) and the first correctness guards `IndexManager.search` has ever had.

### Added
- `edgeproc_core.vector_mgmt.conformance.assert_vector_index_conformance` — a
  conformance suite a third-party backend author runs against their own
  `VectorIndex`. 0.3.0 told implementers that `delete()` and `get_stats()` must
  accept **and apply** `filters`, and gave them no way to check; this is that check.
  Point it at your index factory and it raises `AssertionError` naming every
  property you break:

  ```python
  from edgeproc_core.vector_mgmt.conformance import assert_vector_index_conformance

  async def test_my_backend_is_conformant():
      await assert_vector_index_conformance(my_index_factory)
  ```

  Pass `partition_key_name="org_id"` if you do not partition on `tenant_id`. It
  seeds two partitions into one physical index, gives every row the same vector so
  distance ranking cannot be what separates them, and runs seven checks — the
  load-bearing two being that a scoped `delete()` leaves a neighbouring partition's
  rows intact and a scoped `get_stats()` counts only its own. An accept-and-ignore
  backend fails exactly those two. It does not grade recall, latency, `rebuild()`,
  or tombstone attribution. See
  [Implementing your own backend](README.md#implementing-your-own-backend).

### Fixed
- **`IndexManager.insert` now stamps the `partition_key` argument into any row that
  carries no key of its own.** Routing fell back to that argument, but `search`,
  `delete` and `get_stats` all filter on row *metadata* — so a row inserted as
  `insert([row], partition_key="acme")` without a `tenant_id` landed in acme's index
  and was still invisible to acme's search, uncounted by acme's stats, and
  **undeletable by acme's scoped delete**. Only an unscoped administrative delete
  could reach it. Nothing raised; the row simply vanished. Any consumer keyed on
  something other than `tenant_id` (say `org_id`) hit this hardest, because
  `VectorEmbedding.get_partition_key` falls back to the deprecated `tenant_id`
  *field* only when the key is literally named `tenant_id`.

  The stamp lands on a copy, so your embedding objects come back unmutated, and a
  row that supplies its own key keeps it — routing follows the row, so the metadata
  must too. Stamping cannot widen a scope: the caller already declared those rows
  belong to `partition_key`, and they already routed into its partition. This only
  makes the metadata agree with the routing that had already happened. Behaviour is
  unchanged for every row that already carried its key and for every `insert` call
  that passes no `partition_key`.
- `MockVectorIndex.search` in `tests/conftest.py` applied no filter at all: its
  `continue` skipped to the next *filter key* instead of the next row, so every row
  came back whatever was asked for. Found by pointing the new conformance suite at
  it, which is the point of shipping one. The published `InMemoryVectorIndex` was
  never affected, and `tests/test_tenant_isolation.py` — which guards the README's
  isolation claim — already ran against that real backend rather than this double.
  No existing test depended on the broken behaviour.

## [0.3.0] — 2026-08-03

A minor bump, not a patch, because it changes the `VectorIndex` protocol. The
README's partitioning promise is that a scoped query returns "top-k for that owner
and nobody else"; `search` kept it and `delete`/`get_stats` did not. Both took a
`partition_key`, used it only to choose which index to visit, and applied no
filter. Bucket collisions are expected by design, so the index a key routes to
routinely holds other keys' rows — which made a scoped delete a cross-tenant
delete. Closing that meant adding `filters` to two protocol methods, so callers
of `IndexManager` need no change and implementers of `VectorIndex` do.

### Changed
- **BREAKING for `VectorIndex` implementers:** `VectorIndex.delete()` and
  `VectorIndex.get_stats()` now take a `filters: Metadata | None = None` argument,
  and `IndexManager` passes the partition filter through it. Every implementation
  of the protocol (FAISS, pgvector, hnswlib, an in-house adapter) must accept
  **and apply** `filters`. A backend that accepts it and ignores it still
  type-checks, still passes its own tests, and silently reintroduces cross-tenant
  data destruction — a scoped `delete()` erases the neighbouring partition's rows
  again, and a scoped `get_stats()` counts them again. The default makes the
  signature change source-compatible, which is exactly why the failure is quiet:
  audit each backend rather than trusting the build. No exported symbol was added,
  renamed, or removed — `tests/public_api.json` is untouched — so nothing about
  this break is visible to an import-level check.
- `rebuild_if_needed` stays deliberately unscoped and now says so. Compaction is a
  property of a physical index — a slice of a shared index cannot be rebuilt on its
  own — so its `partition_key` selects which index to maintain and nothing more.
  Pinned by a test rather than left as an unstated asymmetry.

### Fixed
- **`IndexManager.delete()` and `IndexManager.get_stats()` now honour
  `partition_key`.** For callers this is purely a bug fix: a scoped call finally
  does what its argument always said, with no code change on their side. A
  `tenant_a`-scoped delete used to destroy `tenant_b`'s rows, and `tenant_a`-scoped
  stats used to count `tenant_b`'s vectors. Reproduced against `num_buckets=1`: a
  scoped delete of two ids left the neighbouring tenant with one row of three, and
  a scoped `vector_count` read 3 where 2 had been inserted. All three calls now
  compose the same filter, so a caller cannot destroy or count a row a scoped
  `search` would not show it. A scoped delete that matches nothing also leaves no
  tombstone, so one partition can no longer block an id another has yet to insert.

## [0.2.3] — 2026-08-01

The first release cut on a repaired publish path. No runtime code changed;
`edgeproc_core` at 0.2.3 is byte-for-byte the library 0.2.2 was.

`v0.2.2` was tagged and its release run went red before it built anything. The
release job checked out with Actions' default depth-1 clone, so the gate ran
history-backed checks against a repository holding exactly one commit: it declared
the commit SHA the docs pin "does not resolve to a commit in this repository", and
skipped changelog provenance for want of tags. That SHA was never missing — the
checkout simply could not see it. 0.2.2 did reach PyPI in the end, but only after
its tag was deleted and re-cut against the fix, and a tag that gets repointed is
not a pin. 0.2.3 ships from a tag that was right the first time.

### Fixed
- **The release job checks out full history (`fetch-depth: 0`).** `ci.yml` had
  carried that input since it was written; inlining the publish job — needed so
  PyPI's Trusted Publisher sees this repository's own `job_workflow_ref` — copied
  the steps but not the input. Same gate, two different clones, two different
  answers, and the disagreement could only ever surface at a tag.
- **A guard that cannot tell now says so instead of guessing.** On a shallow clone
  `git rev-parse` fails identically for a ref that does not exist and one that was
  never fetched, so the install-ref check no longer reports the first when it means
  the second. It fails closed, names shallowness as the cause, and names the fix.
  A ref genuinely absent from a full clone still fails, exactly as before.

### Added
- **Two regression guards, driven against real clones.** The shallow-versus-missing
  distinction is tested by building a two-commit repository whose commits straddle
  the package rename and cloning it once at `--depth 1` and once in full — nothing
  about Git is mocked. A second guard asserts that every workflow job running
  `poe gate` checks out with `fetch-depth: 0`, so the input cannot be dropped again
  without CI going red; it is driven by four synthetic workflows that each lose full
  history a different way, including one where `fetch-depth: 0` appears only inside
  a comment.

## [0.2.2] — 2026-08-01

A metadata-only release whose entire job is to make PyPI show the right project.
`[project.urls]` is per-release metadata: PyPI renders whatever the *latest* release
declared and offers no way to edit it afterwards, so the identity fix already merged
under `[Unreleased]` could not reach
[the listing](https://pypi.org/project/edgeproc-core/) until a version shipped. Until
this release every sidebar link on that page pointed at `hseshadr/shared-libs-python`
and 301'd to the real repository. No runtime code changed; `edgeproc_core` at 0.2.2 is
byte-for-byte the library 0.2.1 was.

### Changed
- **Public surfaces now name the canonical repository, `hseshadr/edgeproc-core`.**
  At `0.2.1` only the distribution and import names moved; the GitHub repository
  kept its old slug, so badges, clone commands, install URLs, and `[project.urls]`
  still said `shared-libs-python`. The repository has since been renamed, and
  GitHub *redirects* the old slug — so none of those links ever 404'd, they just
  showed a cold reader the wrong project name. `[project.urls]` is what PyPI
  renders in its sidebar, which made the stale identity visible on the listing
  itself. Released sections below keep the old name on purpose: they are history.

### Added
- **`tests/public_api.json` — the exported surface is now a checked-in contract.**
  This package is the bottom of the dependency spine, so a refactor that renamed
  or deleted a public symbol would break downstream repos at *their* import time
  while this repository's own suite stayed green. The golden file records every
  exported name **and every class member this package declares**, so renaming
  `IndexManager.search` fails the build rather than shipping. Inherited machinery
  is excluded, so a dependency bump cannot turn the guard red spuriously.
  Regenerate an intentional change with `uv run python -m tests.test_public_api`.
- **A regression guard for the package identity.** `test_docs_contract.py` now
  fails if any public surface reintroduces the pre-rename slug.

## [0.2.1] — 2026-07-21

First release published to PyPI as
[`edgeproc-core`](https://pypi.org/project/edgeproc-core/), so the short
`pip install edgeproc-core` form now works. Install docs switch to PyPI-first;
the pinned-commit git install remains documented as the from-source path.

### Changed
- **BREAKING: renamed to `edgeproc-core` (import package `edgeproc_core`).**
  The old name described this repository's *role* in a workspace, not a
  product, and a published PyPI name is permanent — so the rename had to land
  before the first publish. Update imports (`shared_libs_python` →
  `edgeproc_core`) and the dependency spec (`shared-libs-python` →
  `edgeproc-core`). The GitHub repository, its URLs, and the local directory
  are deliberately unchanged; only the distribution and import names moved.
  Released sections below keep the old name on purpose: they are history.

### Added
- **A wrong distribution name can no longer degrade `__version__` silently.**
  Both `__init__.py` files resolve `__version__` through
  `importlib.metadata.version(...)` and swallow `PackageNotFoundError` into a
  `0.0.0+unknown` fallback. A rename that missed a lookup string would still
  import, still type-check, and still pass every other test — while reporting a
  fake version. `tests/test_version.py` now asserts the resolved version is not
  the fallback *and* that every lookup site names the distribution
  `pyproject.toml` actually declares, so the two can never drift apart again.
- **Operating contract and repeatable benchmark.**
  `docs/OPERATIONS.md` now makes the package's trust, privacy, recovery, and
  performance ownership explicit; `benchmarks/benchmark.py` records fixed
  p50/p95 budgets for 10,000-item routing and the in-memory reference search.
- **Tenant isolation is proven under forced bucket collision.** The README's
  central promise — "nobody ever sees anyone else's results" — was only tested
  end-to-end for `GlobalPartitionStrategy`, never for the case bucketing
  creates by design once tenants outnumber buckets. `tests/test_tenant_isolation.py`
  forces the worst case (`num_buckets=1`, so every key collides into one index)
  and asserts a scoped read still returns only its own rows, for the default
  `tenant_id` key and a custom one. Each isolation test is paired with a
  non-vacuity assertion that the collision really happened. Isolation holds.
- **Released changelog sections are immutable, and a test enforces it.**
  `tests/test_changelog_provenance.py` compares every released (non-`Unreleased`)
  section at `HEAD` against the same section at its own tag and fails on any
  edit, so checking out `vX.Y.Z` always reproduces what `HEAD` calls `X.Y.Z`.
- **Runnable examples for the two-tier strategy and the errors module.**
  `examples/two_tier_partition.py` (hot/cold routing plus a maintenance
  `rebuild_if_needed` pass) and `examples/canonical_errors.py` (`Registry.codes`,
  `Registry.classify`, `ProblemDetails.to_dict`). Both are wired into
  `examples/run_loop.sh` and executed by the gate, so a documented capability
  can no longer be shipped without a path a reader can actually run.
- **Index-config bounds.** `IndexConfig.m`, `ef_construction`, `ef_search`, and
  `dimension` are `Field(gt=0)`, so a nonsensical value is rejected at
  construction instead of reaching a backend.

### Changed
- **Public status now matches the released `0.2.0` package.** README install
  examples and `SECURITY.md` supported-version policy no longer point at the
  stale `0.1.4`/`0.1.x` line; production-backend targets are labeled as
  consumer guidance rather than library SLA claims.
- **Workflow actions are immutable.** CI, security audit, artifact handoff,
  Codecov, gitleaks, and GitHub release actions are pinned to full commit SHAs,
  with a regression test that rejects moving tags.
- **The gate now measures branch coverage.** `--cov-branch` was never passed, so
  the "98.62% branch coverage" the README published was really *statement*
  coverage. The gate measures branches now and the README publishes the real
  branch figure — **98.41%**, still clear of the 90% floor. The floor was not
  lowered to accommodate the stricter measurement.
- **Benchmark figures re-measured, dated, and attributed to hardware.** The
  published numbers were a best-of-many point estimate that a fresh run did not
  reproduce. README and `docs/OPERATIONS.md` now carry a representative run with
  the observed spread, the machine, the date, and the repro command, guarded by
  `tests/test_benchmark_claims.py`.
- **The errors module is documented.** `errors/` is 44% of production code but
  the word "error" appeared nowhere in `README.md`. It now has a section with a
  plain-language explanation and a runnable example.

### Fixed
- **Invalid bucket counts now fail at construction.**
  `BucketedPartitionStrategy` rejects zero and negative `num_buckets` values at
  the public boundary instead of failing later during routing with a modulo
  error or producing invalid negative bucket identifiers.
- **Workflow security test no longer passes vacuously.** It globbed `*.yml`
  only, so a `deploy.yaml` with an unpinned action would never be inspected. It
  now covers `*.yaml` too and asserts a non-zero count of examined references.
- **Dead `types-all` pre-commit pin replaced.** The package has been a no-op
  stub for years; the mypy hook now pulls `pydantic` (the only dependency with
  types that matter here), and the hook revisions track the pinned tool
  versions so pre-commit and the gate agree.

## [0.2.0] — 2026-07-14

### Added
- **`shared_libs_python.errors` — canonical errors module.** The Python mirror
  of the `@edgeproc/errors` TS package, so a failure carries the same stable
  code and RFC 9457 shape on both sides of the portfolio. An app registers its
  own catalog with `define_errors(...)`, classifies a raw transport/LLM failure
  into one of its codes (`Registry.classify`), describes it through its own
  i18n with the catalog English as fallback (`Registry.describe`), and
  serializes to Problem Details (`Registry.to_problem_details` → the frozen
  `ProblemDetails` dataclass). The optional `starter_pack` supplies 18 universal
  codes (provider/config/network/timeout/device/integrity/internal) so a site
  need not re-declare the common ones. Duplicate codes raise `DuplicateCodeError`
  at registration. Public surface: `define_errors`, `Registry`, `starter_pack`,
  `ProblemDetails`, `Catalog`/`CatalogEntry`/`Category`/`ErrorCode`/`MatchRule`/
  `Params`/`ParamValue`/`TFunction`, `CanonicalError`, and the raw helpers
  `http_status_of`/`error_name_of`/`error_text_of`. Additive — no change to any
  existing module; this is the minor-version feature behind a 0.2.0 tag.

## [0.1.4] — 2026-07-13

### Changed
- **`IndexConfig.distance_metric` is now a typed literal, not a bare string.**
  The field was `str = "cosine"` with a `# cosine, l2, inner_product` comment
  carrying the invariant. It is now `Literal["cosine", "l2", "inner_product"]`
  (exposed as the `DistanceMetric` alias), so Pydantic rejects an unsupported
  metric at construction and `mypy` catches an invalid literal statically.
  Public behavior for the three documented metrics is unchanged.
- **Releases now require the full quality gate.** The publish workflow's
  `test` job ran pytest only and gated nothing — a tag push could publish
  even with failing checks. It is replaced by a `gate` job that mirrors CI
  (`uv run poe gate`: ruff lint, format check, mypy strict, xenon A, pytest
  with ≥90% coverage), and both `build` and `release` `needs:` it. Nothing
  publishes unless the gate passes on the tagged commit.

### Fixed
- **Timezone-aware `created_at` timestamps no longer raise `TypeError`.**
  `TwoTierPartitionStrategy` compared parsed timestamps against a naive
  cutoff, so any aware timestamp (e.g. a `Z` or `+00:00` suffix — the common
  case for stored ISO-8601) crashed classification. The contract is now
  explicit: all comparisons happen in UTC; both aware and naive `created_at`
  values are accepted, and naive values are interpreted as UTC. The lenient
  edges are unchanged (missing → hot, malformed → cold).
- **Two-tier rebuild no longer crashes.** `IndexManager.rebuild_if_needed`
  routed rebuilds by `stats.index_name` ("hot_index"/"cold_index"), which
  `TwoTierPartitionStrategy.get_index` rejects — it only accepts the
  partition names "hot"/"cold" — so any two-tier rebuild raised `ValueError`.
  Rebuilds now iterate partition names and pair each index with its own
  stats, which is correct for every strategy regardless of how it names the
  indexes it hands to the factory.
- **Concurrent lazy index creation no longer loses writes.** All three
  partition strategies raced on first access: two concurrent `get_index`
  calls could each create an index, with the loser's instance (and any writes
  applied to it) silently replaced. Creation is now guarded by an
  `asyncio.Lock` with a double-checked fast path — the factory runs exactly
  once per partition and every concurrent caller receives the same instance.
- **`BucketedPartitionStrategy` routing is now actually deterministic.** Bucket
  ids are computed from a SHA-256 digest of the UTF-8 encoded partition key
  instead of Python's builtin `hash()`, which is randomized per process
  (PYTHONHASHSEED). **Breaking-behavior note:** bucket assignments change for
  anyone who persisted them — but prior assignments were already unstable
  across processes (every restart could re-route every key), so this is
  strictly a fix. Re-partition persisted data once on upgrade; assignments are
  now stable across processes, machines, and Python versions.

## [0.1.3] — 2026-07-11

Standards-alignment release — Wave-0 pilot of the portfolio house standard
(`ENGINEERING-STANDARDS.md`). No library code changes; the public API is
identical to 0.1.2.

### Changed
- Renamed the composite quality task `poe quality` → `poe gate` and added the
  missing `ruff format --check` step (as `poe fmt-check`), so the local gate
  mirrors CI exactly in both directions. No `poe quality` alias kept.
- CI now runs `uv run poe gate` directly. Previously the xenon complexity step
  ran only locally and the format check ran only in CI — both one-sided drifts
  are gone.
- Bumped CI actions to the house floor: `actions/checkout@v5`,
  `actions/setup-python@v6`, `astral-sh/setup-uv@v8`,
  `codecov/codecov-action@v5`.
- Restructured the README into the two-altitude shape: plain-language front
  door, technical depth under "Under the hood (for developers)".
- Dev-dependency security fixes from the first pip-audit run:
  pygments → 2.20.0 (CVE-2026-4539), pytest → 9.1.1 (PYSEC-2026-1845);
  replaced yanked numpy 2.4.0 → 2.5.1.

### Added
- Full-history gitleaks secret-scan job in CI (`gitleaks/gitleaks-action@v3`).
- Weekly `security-audit.yml` workflow running pip-audit over the locked
  dependency export.
- `.github/dependabot.yml` — weekly, grouped updates for GitHub Actions and
  the uv lockfile.
- `CLAUDE.md`: "Quality Gates (Non-Negotiable)" section with scars, and the
  house-standard §8 WASM/edge-compute N/A declaration.

## [0.1.2] — 2026-06-19

Public open-source release (MIT). Part of the `edge-reco → edge-proc →
shared-libs-python` stack going public together; live demo at https://edge-reco.com.

### Added
- `shared_libs_python.vector_mgmt.testing` — `InMemoryVectorIndex` reference
  implementation and `in_memory_factory`, so the bundled `examples/` run
  end-to-end against a fresh checkout.
- `examples/run_loop.sh` — single-command end-to-end demo walking all three
  examples.

### Changed
- README cross-links the three-repo stack and states its role (the
  vector-partitioning protocol edge-proc's FAISS runtime builds on).
- Root `README.md` rewritten for cold-reader clarity: 4-part TL;DR, ≤15-line
  teaser quickstart, source-tree diagram aligned to the actual layout.
- `examples/basic_usage.py`, `custom_partition_key.py`,
  `composite_partition_key.py` now use the bundled in-memory factory and
  produce real output (previously crashed with `NoneType has no attribute
  'insert'`).
- `CLAUDE.md`: dropped stale "Placeholder Modules" section
  (`vector_mgmt/indexing/`, `vector_mgmt/reindex/` were removed in v0.1.1);
  documented the `testing` module; fixed `metadata: dict[str, Any]` to
  `dict[str, Scalar]`.

### Removed
- Stale root-level review documents (`PROJECT_REVIEW.md`, `GITHUB_REVIEW.md`,
  `REVIEW_SUMMARY.md`) from the pre-v0.1.1 review cycle.

## [0.1.1] - 2026-05-21

### Changed
- Tightened the entire public surface to the strict python-quality bar: `mypy --strict` clean, Radon Grade A complexity (cyclomatic ≤ 5), all functions ≤ 15 lines, no `Dict[str, Any]` in user code.
- Replaced ad-hoc `dict[str, Any]` metadata/filter types with a `Scalar` / `Metadata` type alias pair (`Scalar = str | int | float | bool | None`).
- Introduced `IndexFactory` Protocol replacing the previous `Callable[..., Awaitable[VectorIndex]]` annotation.
- `IndexManager.search` refactored into `_compose_filters` + `_merge_top_k` helpers (Grade A).
- `TwoTierPartitionStrategy.get_partitions` refactored into a `_classify_embedding` helper (Grade A). Behavior preserved (naive `datetime.now()`; missing/non-string `created_at` → hot; parse error → cold).
- Magic-number thresholds in `IndexManager.rebuild_if_needed` named with `Final[float]`.
- Moved unused runtime extras (`pgvector`, `sqlalchemy[asyncio]`, `numpy`) from required dependencies to `[project.optional-dependencies].pgvector`. Default install is now lean (pydantic only).
- Added `poe` tasks: `lint`, `fmt`, `typecheck`, `complexity`, `test`, `quality`.
- Updated `pyproject.toml` author from "Vector Management Team" to "Harish Seshadri".

### Removed
- Empty `shared_libs_python.vector_mgmt.indexing` and `shared_libs_python.vector_mgmt.reindex` submodules (referenced nothing; no public symbols exported).
- "Reindexing utilities" feature claim from the README.

### Added
- `xenon`, `radon`, `poethepoet` as dev dependencies for the strict quality gate.

## [0.1.0] - 2025-01-15

### Added
- Initial release of shared-libs-python
- Generic partition key support (tenant_id, user_id, org_id, etc.)
- Three partitioning strategies:
  - `GlobalPartitionStrategy`: Single global index with metadata filtering
  - `BucketedPartitionStrategy`: Hash-based bucketing for scale
  - `TwoTierPartitionStrategy`: Hot/cold tier separation
- `IndexManager` for coordinating vector indices
- `VectorIndex` protocol for abstract index interface
- Type-safe implementation with Pydantic models
- Backward compatibility with `tenant_id` field
- Custom partition key extractors support
- Comprehensive documentation

### Features
- Generic partition key extraction from metadata
- Support for any partition key name
- Composite partition keys via custom extractors
- Full type hints and mypy strict compliance
- Protocol-based design for extensibility

[Unreleased]: https://github.com/hseshadr/edgeproc-core/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/hseshadr/edgeproc-core/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/hseshadr/edgeproc-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/hseshadr/edgeproc-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/hseshadr/edgeproc-core/compare/v0.2.3...v0.3.0
[0.2.3]: https://github.com/hseshadr/edgeproc-core/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/hseshadr/edgeproc-core/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/hseshadr/edgeproc-core/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/hseshadr/edgeproc-core/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/hseshadr/edgeproc-core/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/hseshadr/edgeproc-core/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/hseshadr/edgeproc-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/hseshadr/edgeproc-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/hseshadr/edgeproc-core/releases/tag/v0.1.0
