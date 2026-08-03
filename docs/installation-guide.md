# Installation guide

**TL;DR.** `edgeproc-core` supports Python 3.13+ and is published on
[PyPI](https://pypi.org/project/edgeproc-core/):

```bash
uv pip install edgeproc-core
```

That installs the real library. To see its complete partition-and-search path
against realistic in-memory data, clone the repository and run:

```bash
bash examples/run_loop.sh
```

## Requirements

- Python 3.13 or newer
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`

Create a clean environment with `uv`:

```bash
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate
```

## Install a pinned version

Pin an exact release so a later publish cannot silently change an application's
dependency:

```bash
# uv
uv pip install "edgeproc-core==0.4.0"

# pip
python -m pip install "edgeproc-core==0.4.0"
```

For `pyproject.toml`:

```toml
[project]
requires-python = ">=3.13"
dependencies = [
  "edgeproc-core>=0.4.0",
]
```

For `requirements.txt`:

```text
edgeproc-core==0.4.0
```

### Installing from source instead

To build from the repository rather than PyPI, pin a full commit SHA — Git
cannot repoint it, so it is exactly as immutable as a release:

```bash
# uv
uv pip install "edgeproc-core @ git+https://github.com/hseshadr/edgeproc-core.git@6cdf8475b223262821622a021c561aed9213a472"

# pip
python -m pip install "edgeproc-core @ git+https://github.com/hseshadr/edgeproc-core.git@6cdf8475b223262821622a021c561aed9213a472"
```

### Why do source pins use a commit and not a tag?

Tags `v0.2.0` and older were cut *before* the import package was renamed from
`shared_libs_python` to `edgeproc_core`. Installing one of those tags therefore
succeeds but gives you the old module name, and the verification snippet below
fails with `ModuleNotFoundError: No module named 'edgeproc_core'`. Pin a commit
at or after the rename, or install from PyPI as shown above.

Install `0.4.0` or newer. `0.2.1` and `0.2.2` carry a cross-tenant delete defect —
a `tenant_a`-scoped `delete()` destroyed `tenant_b`'s rows — fixed in `0.3.0`, and
`0.3.0` itself ships without the `conformance` module its README documents.

## Verify the installation

```bash
python - <<'PY'
import edgeproc_core
from edgeproc_core import BucketedPartitionStrategy, VectorEmbedding

print(f"edgeproc-core {edgeproc_core.__version__}")
print(BucketedPartitionStrategy)
print(VectorEmbedding(entity_id="example", embedding=[0.1, 0.2]))
PY
```

Then follow the root [README quickstart](../README.md#60-second-quickstart) or
run the bundled end-to-end examples:

```bash
bash examples/run_loop.sh
```

## Development installs

Contributors should clone the repository so the lockfile and complete quality
gate are available:

```bash
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core
uv sync --all-extras --dev
uv run poe gate
```

Installing the moving `main` branch is intentionally a development-only path:

```bash
uv pip install git+https://github.com/hseshadr/edgeproc-core.git@main
```

## Upgrade or reinstall

For a PyPI install:

```bash
uv pip install --upgrade edgeproc-core
```

For a from-source install, change the pinned commit, then force the reinstall.
For the currently documented pin:

```bash
uv pip install --upgrade --force-reinstall \
  "edgeproc-core @ git+https://github.com/hseshadr/edgeproc-core.git@6cdf8475b223262821622a021c561aed9213a472"
```

## Troubleshooting

### Python version mismatch

If the resolver says the current interpreter does not satisfy Python 3.13,
create the environment explicitly:

```bash
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate
```

### Commit not found

Confirm the pinned commit exists on the public repository:

```bash
git ls-remote https://github.com/hseshadr/edgeproc-core.git | \
  grep 6cdf8475b223262821622a021c561aed9213a472
```

### `ModuleNotFoundError: No module named 'edgeproc_core'`

You almost certainly installed the `v0.2.0` tag (or older) rather than a PyPI
release or the pinned commit. Those tags predate the rename and ship the old
`shared_libs_python` module. Check what is actually installed and reinstall
from PyPI or the pinned commit:

```bash
uv pip list | grep -i -E "edgeproc|shared"
```

### Cached older version

Prefer an explicit forced reinstall over clearing the entire shared `uv` cache:

```bash
uv pip install --upgrade --force-reinstall \
  "edgeproc-core @ git+https://github.com/hseshadr/edgeproc-core.git@6cdf8475b223262821622a021c561aed9213a472"
```

The supported release line and vulnerability-reporting process are documented
in [SECURITY.md](../SECURITY.md).
