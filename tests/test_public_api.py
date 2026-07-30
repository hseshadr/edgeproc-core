"""Public-API guard: the exported surface is a contract, pinned in a golden file.

This package is the bottom of the portfolio spine — `edge-proc`, `edge-reco`,
and every downstream repo import from it. A refactor that renames or deletes an
exported symbol breaks those repos at *their* import time, not here, so nothing
in this repository's own suite would notice. `tests/public_api.json` closes that
hole: it records every public name this package exports, and the checks below
fail when one disappears.

Why names *and* class members: a guard that only pinned module-level names would
stay green while `IndexManager.search` was renamed to `.query` — it would be
measuring the shape of the API (nine exported classes) instead of the property
that matters (the callers still resolve). Members are therefore pinned too.

Only symbols this package itself declares are recorded — inherited machinery
(pydantic's `model_dump`, …) is deliberately excluded so a dependency bump
cannot turn this guard red for a change that breaks no caller.

Regenerating after an *intentional* API change::

    uv run python -m tests.test_public_api

Review that diff like any other contract change: a removed line is a breaking
change and needs a major/minor bump plus a CHANGELOG entry.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path
from types import ModuleType

import edgeproc_core

PACKAGE = "edgeproc_core"
GOLDEN = Path(__file__).with_name("public_api.json")

#: A symbol that must always be exported. If the collector silently starts
#: returning nothing, every subset check below would pass vacuously; this
#: anchor makes that failure mode loud.
ANCHOR = ("edgeproc_core", "IndexManager.search")


def _module_names() -> list[str]:
    """Every importable module in the shipped package, root included."""
    walked = pkgutil.walk_packages(edgeproc_core.__path__, prefix=f"{PACKAGE}.")
    return sorted([PACKAGE, *(info.name for info in walked)])


def _is_owned(module: ModuleType, name: str) -> bool:
    """True when `name` is defined by `module` rather than imported into it."""
    obj = getattr(module, name)
    if inspect.ismodule(obj):
        return False
    origin = getattr(obj, "__module__", None)
    return origin in (None, module.__name__)


def _exported_names(module: ModuleType) -> list[str]:
    """The names a downstream repo may import from `module`."""
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return sorted(declared)
    return sorted(n for n in vars(module) if not n.startswith("_") and _is_owned(module, n))


def _declared_on(base: type) -> set[str]:
    """Public attributes and annotated fields declared directly on one class."""
    declared = (*vars(base), *inspect.get_annotations(base))
    return {name for name in declared if not name.startswith("_")}


def _owned_bases(cls: type) -> list[type]:
    """The part of `cls`'s MRO this package defines; inherited machinery excluded."""
    return [b for b in cls.__mro__ if str(getattr(b, "__module__", "")).startswith(PACKAGE)]


def _own_members(obj: object) -> list[str]:
    """Public attributes and annotated fields this package declares on a class."""
    if not inspect.isclass(obj):
        return []
    names: set[str] = set()
    for base in _owned_bases(obj):
        names.update(_declared_on(base))
    return sorted(names)


def _entries(module: ModuleType) -> list[str]:
    """Flat `name` / `name.member` entries describing one module's public surface."""
    entries: list[str] = []
    for name in _exported_names(module):
        entries.append(name)
        entries.extend(f"{name}.{member}" for member in _own_members(getattr(module, name)))
    return sorted(entries)


def collect_public_api() -> dict[str, list[str]]:
    """The live public surface, keyed by module — the same shape as the golden file."""
    return {name: _entries(importlib.import_module(name)) for name in _module_names()}


def _load_golden() -> dict[str, list[str]]:
    assert GOLDEN.exists(), (
        f"{GOLDEN.name} is missing. It is the checked-in record of this package's "
        f"public API; regenerate it with `uv run python -m tests.test_public_api`."
    )
    parsed: dict[str, list[str]] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return parsed


def test_the_golden_file_is_not_vacuous() -> None:
    """Guard the guard: an empty or truncated golden would pass every check below."""
    golden = _load_golden()
    module, symbol = ANCHOR

    assert golden, "the golden file records no modules at all"
    assert symbol in golden.get(module, []), (
        f"{module}:{symbol} is absent from the golden file. Either the collector "
        f"stopped seeing class members or the golden was regenerated from a broken "
        f"tree — both make the subset checks below meaningless."
    )


def test_no_public_symbol_disappeared() -> None:
    """BREAKING-CHANGE guard: every recorded symbol must still be exported."""
    golden, live = _load_golden(), collect_public_api()
    missing = {
        module: sorted(set(names) - set(live.get(module, [])))
        for module, names in golden.items()
        if set(names) - set(live.get(module, []))
    }

    assert not missing, (
        f"Public API symbols were removed or renamed: {json.dumps(missing, indent=2)}\n"
        f"Downstream repos import these; deleting one breaks them at import time. "
        f"If the removal is intentional, bump the version, add a CHANGELOG entry, "
        f"then regenerate with `uv run python -m tests.test_public_api`."
    )


def test_every_shipped_module_is_recorded() -> None:
    """A new module must be registered, so it cannot ship unguarded."""
    golden, live = _load_golden(), collect_public_api()

    assert sorted(live) == sorted(golden), (
        f"Module set drifted. Only in the package: {sorted(set(live) - set(golden))}; "
        f"only in the golden file: {sorted(set(golden) - set(live))}. "
        f"Regenerate with `uv run python -m tests.test_public_api`."
    )


def test_new_public_symbols_are_recorded() -> None:
    """Additions are not breaking, but they must be a deliberate, reviewed diff."""
    golden, live = _load_golden(), collect_public_api()
    added = {
        module: sorted(set(names) - set(golden.get(module, [])))
        for module, names in live.items()
        if set(names) - set(golden.get(module, []))
    }

    assert not added, (
        f"New public API symbols are not recorded: {json.dumps(added, indent=2)}\n"
        f"Anything exported is a promise to downstream repos. Regenerate with "
        f"`uv run python -m tests.test_public_api` to accept them."
    )


if __name__ == "__main__":  # pragma: no cover - maintenance entry point
    GOLDEN.write_text(json.dumps(collect_public_api(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN}")
