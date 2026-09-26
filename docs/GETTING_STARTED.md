# Getting started for developers

This takes you from nothing to a green local build and your first change. Every command here
was run from a fresh clone on macOS (Apple M3 Pro) with uv 0.8.5; the times are from that run.

## 1. What you need

- **Python 3.13 or newer.** You don't have to install it yourself: uv downloads it.
- **[uv](https://docs.astral.sh/uv/)**, the Python package manager this repo uses. Install it
  with `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`.
- **git.**
- Optional: **Docker and the [Dagger](https://docs.dagger.io/install) CLI 0.21.8**, only if you
  want to run the exact CI container locally (step 3).

Known traps:

- **Do not make a shallow clone** (`git clone --depth 1`). The changelog and install-pin tests
  compare files against old release tags, so a shallow clone fails
  `tests/test_changelog_provenance.py` with an error. Clone the full history.
- **Run the whole check, not only `pytest`, before pushing.** `poe gate` also checks that the
  coverage figures in [ARCHITECTURE.md](ARCHITECTURE.md) still match the real run. That step
  reads `coverage.xml`, so it only works after the tests have run.

## 2. Clone, install, run the tests

```bash
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core
uv sync
```

Clone and `uv sync` took about 2 seconds each (uv had its cache warm; a first-ever install
downloads Python and a few packages and takes longer). `uv sync` creates `.venv/` with the
package installed in editable mode plus the dev tools (pytest, ruff, mypy, poe).

Run the examples, which exercise every partitioning strategy and the error catalog against the
in-memory index:

```bash
bash examples/run_loop.sh
```

Success ends with `All examples ran successfully.`

## 3. The one command that runs everything

```bash
uv run poe gate
```

This is what CI runs. In order: ruff lint, ruff format check, `mypy --strict`, a complexity
check (xenon, every function grade A), the tests with branch coverage (must stay at or above
90%), a check that the coverage figures in [ARCHITECTURE.md](ARCHITECTURE.md) match the run,
and a check that every import shown in the docs works against a freshly built wheel.

From a fresh clone it took 45 seconds; later runs take about 15. Success looks like:

```text
Required test coverage of 90% reached. Total coverage: 99.31%
============================= 380 passed in 15.00s =============================
...
OK: ARCHITECTURE.md coverage claims match the measured run.
...
OK: every documented import resolved inside the wheel
```

CI runs the same thing inside a container through Dagger (the `Dagger` check on every PR). To
run that container locally, with Docker running:

```bash
dagger call ci --commit-sha=$(git rev-parse HEAD)
```

Useful single steps while you work:

```bash
uv run pytest tests/test_errors_raw.py -q --no-cov   # one test file, ~1 second
uv run poe lint        # ruff check
uv run poe fmt         # auto-format
uv run poe typecheck   # mypy --strict
```

## 4. Map of the code

| Path | What it is |
| --- | --- |
| `edgeproc_core/vector_mgmt/core/index_manager.py` | `IndexManager`: routes inserts, adds the owner filter, merges search results |
| `edgeproc_core/vector_mgmt/core/types.py` | `VectorEmbedding`, `IndexConfig`, and the `VectorIndex` protocol a backend implements |
| `edgeproc_core/vector_mgmt/partitioning/strategies.py` | The three strategies: global, bucketed, two-tier |
| `edgeproc_core/vector_mgmt/testing.py` | `InMemoryVectorIndex`, the reference index for tests and examples |
| `edgeproc_core/vector_mgmt/conformance.py` | `assert_vector_index_conformance`, which grades someone's own backend |
| `edgeproc_core/errors/` | The error module: `registry.py` (classify, describe, serialize), `starter_pack.py` (18 codes), `raw.py` (reads failures of unknown shape) |
| `tests/` | pytest suite; `test_tenant_isolation.py` is the key isolation proof, `test_readme_contract.py` and `test_docs_contract.py` keep the docs honest |
| `tests/public_api.json` | Every exported symbol; `test_public_api.py` fails if one disappears |
| `examples/` | Runnable scripts, driven by `run_loop.sh` |
| `scripts/` | The coverage-figure and documented-import checks used by `poe gate` |

## 5. Make your first change

A typical small change: teach the error module to read an HTTP status from an exception that
carries its response, the way `requests.HTTPError` does (`err.response.status_code`). Today
`http_status_of` only looks at the top-level object.

Branch, then write the failing test first. Add this to the end of `tests/test_errors_raw.py`:

```python
def test_should_read_status_from_a_nested_response() -> None:
    # Given an exception that carries its response, like requests.HTTPError
    raw = SimpleNamespace(response=SimpleNamespace(status_code=402))
    # When the status is read
    # Then the response's status is used
    assert http_status_of(raw) == 402
```

Run just that file and watch it fail:

```bash
git checkout -b fix/status-from-nested-response
uv run pytest tests/test_errors_raw.py -q --no-cov
# FAILED tests/test_errors_raw.py::test_should_read_status_from_a_nested_response
# 1 failed, 11 passed
```

Then make the smallest change in `edgeproc_core/errors/raw.py`, at the end of `http_status_of`:

```python
    response = _read(raw, "response")
    return None if response is None else http_status_of(response)
```

Run the file again (12 passed), then `uv run poe gate`. Add a line under `[Unreleased]` in
[CHANGELOG.md](../CHANGELOG.md). Before opening a PR for a change like this one, check the
TypeScript twin, [@edgeproc/errors](https://github.com/hseshadr/errors): the error codes and
their matching rules are meant to behave the same in both languages.

## 6. Open a pull request

- **Branch names:** `feat/…`, `fix/…`, `docs/…`, `test/…`, `chore/…`, matching the
  [Conventional Commits](https://www.conventionalcommits.org/) type of your commit.
- **Before pushing:** `uv run poe gate` must pass. It mirrors CI exactly.
- **What CI checks:** the `Dagger` workflow runs the same steps in a container on every PR. A
  separate weekly `security-audit.yml` runs pip-audit on the dependencies.
- **What reviewers look for:**
  - a test that fails without your change;
  - a `[Unreleased]` CHANGELOG entry (released sections never change;
    `tests/test_changelog_provenance.py` enforces that);
  - if you touched the public API, a deliberate update of `tests/public_api.json`
    (`uv run python -m tests.test_public_api`);
  - if you changed a published benchmark figure, a fresh measurement recorded in
    `tests/test_benchmark_claims.py`.

More rules are in [CONTRIBUTING.md](../CONTRIBUTING.md).
