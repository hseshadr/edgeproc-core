# Contributing to edgeproc-core

Thank you for your interest in contributing to edgeproc-core! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/hseshadr/edgeproc-core.git
cd edgeproc-core

# Install dependencies
uv sync
uv pip install -e .
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Write clean, type-safe code
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed

### 3. Run the Gate

One command runs everything CI runs — lint, format check, strict type
checking, complexity, and tests with ≥90% coverage. It must pass before you
push:

```bash
uv run poe gate
```

Individual steps while iterating:

```bash
# Run all tests (coverage included via pytest addopts)
uv run pytest

# Run specific test file
uv run pytest tests/test_types.py

# Type checking (strict mode)
uv run poe typecheck

# Linting / auto-format
uv run poe lint
uv run poe fmt
```

### 4. Commit Changes

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git commit -m "feat: add new partition strategy"
git commit -m "fix: correct type hint in IndexManager"
git commit -m "docs: update README with examples"
git commit -m "test: add tests for custom extractors"
```

### 5. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Code Style

### Type Hints

- All functions must have type hints
- Use `mypy --strict` compliance
- Prefer `list[T]` over `List[T]` (Python 3.9+)
- Use `dict[str, Any]` instead of `Dict[str, Any]`

### Code Formatting

- Line length: 100 characters
- Use `ruff` for formatting and linting
- Follow existing code patterns

### Documentation

- Add docstrings to all public functions and classes
- Use Google-style docstrings
- Include type information in docstrings

## Testing Requirements

### Coverage

- Maintain **90%+ code coverage**
- All new code must have tests
- Edge cases should be covered

### Test Structure

- Unit tests in `tests/` directory
- Use descriptive test names: `test_function_name_scenario`
- Use fixtures from `conftest.py` when possible

### Running Tests

```bash
# All tests
uv run pytest

# With coverage report
uv run pytest --cov=edgeproc_core --cov-report=html

# Specific test
uv run pytest tests/test_index_manager.py::TestIndexManager::test_insert
```

## Pull Request Process

1. **Update CHANGELOG.md** under `[Unreleased]` — see the rule below
2. **Ensure the gate passes** (`uv run poe gate` — lint, format check,
   `mypy --strict`, xenon complexity, tests with ≥90% branch coverage)
3. **Update documentation** if needed
4. **Request review** from maintainers

### Released changelog sections are immutable

New entries go under `[Unreleased]`, **never** into an already-released section.
Once `vX.Y.Z` is tagged, that section is history: checking out the tag must
reproduce exactly what `HEAD` says shipped in `X.Y.Z`. Editing a released
section — even just re-dating its header — breaks that, and provable provenance
is the whole point of this stack.

`tests/test_changelog_provenance.py` enforces this by diffing every released
section at `HEAD` against the same section at its tag. If it fails, move your
entry to `[Unreleased]` rather than changing the released text.

Adding a `[X.Y.Z]: …/compare/…` link-reference line to the footer is fine — that
footer is a growing index of releases, not any one release's record.

### Changing the public API

`tests/public_api.json` is a checked-in record of every symbol this package
exports, down to the class members it declares. It exists because this package
sits at the bottom of the dependency spine: deleting or renaming a public symbol
breaks downstream repos at *their* import time, which nothing in this
repository's own suite would otherwise notice.

If `tests/test_public_api.py` fails, read which check failed:

- **A symbol disappeared** — that is a breaking change. It needs a version bump
  and a `[Unreleased]` CHANGELOG entry, not just a regenerated golden file.
- **A symbol was added** — harmless to callers, but anything exported is a
  promise, so record it deliberately.

Either way, accept the change with:

```bash
uv run python -m tests.test_public_api
```

Review the resulting diff like any other contract change; a removed line is the
signal the guard exists to raise.

### Benchmark figures

If you change a number published in `README.md` or `docs/OPERATIONS.md`,
re-measure it (`uv run python benchmarks/benchmark.py`), state the hardware and
date, and update `REFERENCE` in `tests/test_benchmark_claims.py` in the same
commit. That test compares the docs against the recorded measurement — it never
runs the benchmark itself, so it cannot flake on a busy machine.

### PR Checklist

- [ ] Tests added/updated
- [ ] The gate passes (`uv run poe gate`)
- [ ] Documentation updated
- [ ] CHANGELOG.md updated **under `[Unreleased]`**

## Adding New Features

### Partition Strategies

If adding a new partition strategy:

1. Extend `PartitionStrategy` base class
2. Implement required abstract methods
3. Add comprehensive tests
4. Update documentation
5. Add usage examples

### Vector Index Implementations

The library uses a protocol-based design. To add support for a new vector database:

1. Implement the `VectorIndex` protocol
2. Create example implementation in `examples/`
3. Document integration steps
4. Add tests if possible

## Reporting Issues

### Bug Reports

Use the GitHub issue template and include:

- Python version
- Library version
- Steps to reproduce
- Expected behavior
- Actual behavior
- Error messages/logs

### Feature Requests

Include:

- Use case description
- Proposed API design
- Benefits/impact
- Potential implementation approach

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Follow the project's coding standards

## Questions?

- Open an issue for questions
- Check existing issues/PRs first
- Review documentation in `docs/`

Thank you for contributing! 🎉


