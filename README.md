# edgeproc-core

A Python library that keeps each customer's search results separate in a shared index, and gives errors stable codes.

**Python 3.13 or newer: `pip install edgeproc-core`**

[![CI](https://github.com/hseshadr/edgeproc-core/actions/workflows/dagger.yml/badge.svg)](https://github.com/hseshadr/edgeproc-core/actions/workflows/dagger.yml)
[![PyPI](https://img.shields.io/pypi/v/edgeproc-core)](https://pypi.org/project/edgeproc-core/)
[![License](https://img.shields.io/github/license/hseshadr/edgeproc-core)](LICENSE)

Many apps have a "find similar" or document search feature that all their customers share.
Each item is stored as a list of numbers (an embedding) in an index built for that kind of
lookup (a vector index). One index per customer wastes memory once you have thousands of
customers. One shared index means every search, delete and count must be filtered by customer,
and a single missed filter shows, or deletes, someone else's data.

edgeproc-core does that routing and filtering for you. You tag each item with its owner. The
library decides which index the item goes in and adds the owner filter to every call, so a
customer only ever gets their own rows back. It stores nothing itself: you plug in your own
index (FAISS, pgvector, hnswlib and so on), and a test it ships tells you whether your index
really applies the filter. The package also has a small, separate error module that turns
failures like an HTTP 402 or a timeout into one stable code with a message you can show a user.

**Technical docs:** [Architecture](docs/ARCHITECTURE.md) · [Getting started for developers](docs/GETTING_STARTED.md) · [Installation guide](docs/installation-guide.md) · [Operations](docs/OPERATIONS.md)

## Try it

1. Make a folder and install the package from PyPI. This uses [uv](https://docs.astral.sh/uv/),
   which downloads Python 3.13 if you don't have it.

   ```bash
   mkdir try-edgeproc-core && cd try-edgeproc-core
   uv venv --python 3.13
   uv pip install edgeproc-core
   ```

2. Save this as `example.py`. Two customers, acme and globex, each store an identical invoice.
   To make it the hardest case, both are forced into one shared index (`num_buckets=1`).

   ```python
   import asyncio
   from edgeproc_core import BucketedPartitionStrategy, IndexManager, VectorEmbedding
   from edgeproc_core.errors import define_errors, starter_pack
   from edgeproc_core.vector_mgmt.testing import in_memory_factory

   async def main() -> None:
       manager = IndexManager(BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=1))
       for owner in ("acme", "globex"):
           await manager.insert([VectorEmbedding(entity_id=f"{owner}-invoice", embedding=[1.0, 0.0], metadata={"tenant_id": owner})])
       print("acme sees:", await manager.search([1.0, 0.0], k=10, partition_key="acme"))
       print("no filter:", await manager.search([1.0, 0.0], k=10))

   asyncio.run(main())
   errors = define_errors(starter_pack)  # 18 ready-made error codes
   print(errors.to_problem_details(errors.classify({"status": 402})).to_dict())
   ```

3. Run it with `.venv/bin/python example.py`. This is the real output from edgeproc-core
   0.4.3 installed from PyPI:

   ```text
   acme sees: [('acme-invoice', 0.0)]
   no filter: [('acme-invoice', 0.0), ('globex-invoice', 0.0)]
   {'type': 'ai.provider.out_of_credits', 'title': 'Your provider account is out of credits. Add credits and try again.', 'status': 402}
   ```

Both invoices sit in the same index and match the query equally well (a distance of 0.0 means
identical). Searching as acme returns only acme's invoice. A search with no owner is the admin
view and returns both. The last line is the error module: a raw `{"status": 402}` becomes the
code `ai.provider.out_of_credits` with readable text, in the standard JSON error format for web
APIs (RFC 9457 "Problem Details").

To run every example in the repo (each partitioning strategy and the error catalog), clone it,
run `uv sync`, then `bash examples/run_loop.sh`.

## How it works

`IndexManager` takes each item's owner and asks a partitioning strategy which physical index it
belongs in: one shared index, one of N hash buckets, or a recent and an older tier. It then calls
your index there, passing the owner as a filter on every search, delete and count. When a search
spans several indexes, it merges the results into one ranked list. Your index only has to provide
a short list of methods (the `VectorIndex` protocol); there is nothing to subclass. The error
module is separate: `classify` maps a raw failure to a code, `describe` turns the code into text,
and `to_problem_details` turns it into the JSON an API returns.

It is the bottom layer of a few related projects by the same author.
[edge-proc](https://github.com/hseshadr/edge-proc), also on PyPI, depends on this package: it
implements the `VectorIndex` protocol with FAISS and adds shipping signed data to devices.
[edge-reco](https://github.com/hseshadr/edge-reco), an in-browser store search demo, uses both
in its Python backend. [@edgeproc/browser](https://github.com/hseshadr/edgeproc-browser) checks
edge-proc's signed data inside a web page and does not use this package.
[privacy-core](https://github.com/hseshadr/privacy-core) only shares the `@edgeproc` npm name;
it hides personal data from AI prompts and is unrelated. The error codes match the TypeScript
package [@edgeproc/errors](https://github.com/hseshadr/errors).

## What it does not do

- **It is not a search engine.** It ships no production index, only a small in-memory one for
  tests and examples. You bring the index.
- **It is not access control on its own.** An owner name is a routing hint. If your index
  ignores the filter it is given, owners leak into each other's results. Run the conformance
  test (`assert_vector_index_conformance`) against your index, and enforce access in your
  database too.
- **A call with no owner sees everything.** That is the deliberate admin path, for searches and
  deletes alike.
- **It does not measure search quality or speed of your index.** The published timings come
  from the in-memory reference index on one laptop. See
  [What the tests prove](docs/ARCHITECTURE.md#what-the-tests-prove).
- **The two modules are unrelated.** The error codes have nothing to do with search; they just
  ship in the same package.

## When to use something else

| If you | Use |
| --- | --- |
| Have a few large customers and can afford an index each | One index per customer |
| Are committed to one vector database and happy with its own namespaces | That database's built-in multi-tenancy |
| Need search that runs on devices, with signed downloads | [edge-proc](https://github.com/hseshadr/edge-proc), which builds on this |
| Want one partitioning scheme that works across FAISS, pgvector, hnswlib and tests, with a test proving the filter is applied | edgeproc-core |

## Install

```bash
uv pip install edgeproc-core
```

Or add it to your `pyproject.toml`:

```toml
dependencies = ["edgeproc-core==0.4.3"]
```

Check it worked:

```bash
python -c "import edgeproc_core; print(edgeproc_core.__version__)"
# 0.4.3
```

This README describes v0.4.3. The library is in beta: the API may still change before 1.0.
To install from source with a pinned commit, see the [installation guide](docs/installation-guide.md).

## Develop

```bash
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core
uv sync
uv run poe gate
```

`uv run poe gate` runs the same checks as CI: lint, format check, `mypy --strict`, a complexity
check, and the tests, which must keep ≥90% branch coverage. It takes under a minute from a fresh
clone. [Getting started for developers](docs/GETTING_STARTED.md) walks through a first change,
and [CONTRIBUTING.md](CONTRIBUTING.md) covers the PR rules.

## More detail

- [Architecture](docs/ARCHITECTURE.md): routing, the three strategies, the conformance suite,
  the error module, configuration, the security model, and what the tests prove.
- [Getting started for developers](docs/GETTING_STARTED.md): from a fresh clone to a green build
  and your first change.
- [Installation guide](docs/installation-guide.md): pinned installs, source installs, and
  troubleshooting.
- [Vector index design notes](docs/vector-mgmt-architecture.md): index sizing, rebuilds, and
  planned features.
- [Operations](docs/OPERATIONS.md): the security, privacy, reliability and performance contract.
- [Docs index](docs/README.md): a short map of the docs folder.
- [Explore the interactive architecture map](docs/architecture/index.html).
- [Examples](examples/README.md): runnable scripts for each strategy and the error catalog.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
