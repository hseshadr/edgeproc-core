"""Every documented ``edgeproc_core`` import must resolve inside the BUILT WHEEL.

``conformance.py`` merged 14 minutes after the ``v0.3.0`` tag was cut, so the
published 0.3.0 wheel and sdist do not contain it — while ``README.md`` tells
implementers to ``from edgeproc_core.vector_mgmt.conformance import ...``. A
clean-venv ``pip install edgeproc-core==0.3.0`` followed by that import raises
``ModuleNotFoundError``. Nothing in the gate noticed: ``test_docs_contract.py``
asserted only that a bare ``import edgeproc_core`` resolves, which is shape, not
property, and is precisely why the drift shipped.

This builds the wheel, unpacks it, and runs every documented import against that
unpacked tree alone. The load-bearing detail is the provenance check inside the
probe: it proves ``edgeproc_core.__file__`` really lives under the unpacked
wheel *before* running anything, so this can never pass by quietly importing the
working copy sitting right next to it.

Run directly, or as the ``docs-imports`` step of ``uv run poe gate``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCS: tuple[str, ...] = ("README.md", "docs/installation-guide.md")
"""Docs whose fenced blocks a reader copies and runs verbatim."""

FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
"""Any fenced block, in any language: the install guide's Python lives inside a
``bash`` fence as a heredoc, and a reader runs that one too."""

IMPORT_LINE = re.compile(r"^[ \t]*(?:from|import)[ \t]+edgeproc_core\b[^\n]*$", re.M)

MIN_EXPECTED_IMPORTS = 5
"""Non-vacuity floor. An extractor that silently matched nothing would let this
check pass against any wheel at all — the exact failure mode it exists to catch."""

PROBE = """\
import pathlib
import sys

wheel_root = pathlib.Path(sys.argv[1]).resolve()
import edgeproc_core

loaded = pathlib.Path(edgeproc_core.__file__).resolve()
if wheel_root not in loaded.parents:
    sys.exit(f"VACUOUS: edgeproc_core resolved to {{loaded}}, not the wheel at {{wheel_root}}")
{statements}
print("every documented import resolved inside the wheel")
"""


def documented_imports() -> list[str]:
    """Every distinct ``edgeproc_core`` import statement inside a fenced doc block."""
    seen: dict[str, None] = {}
    for doc in DOCS:
        for fence in FENCE.findall((ROOT / doc).read_text(encoding="utf-8")):
            for line in IMPORT_LINE.findall(fence):
                seen[line.strip()] = None
    return list(seen)


def build_wheel(out_dir: Path) -> Path:
    """Build the wheel this release would publish and return its path."""
    subprocess.run(  # noqa: S603
        ["uv", "build", "--no-build-isolation", "--wheel", "--out-dir", str(out_dir)],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one wheel in {out_dir}, found {wheels}")
    return wheels[0]


def unpack(wheel: Path, dest: Path) -> Path:
    """Extract ``wheel`` into ``dest`` and return the root imports resolve from."""
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(dest)
    return dest


def _probe_env(wheel_root: Path) -> dict[str, str]:
    """A child environment where the unpacked wheel shadows any installed copy."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(wheel_root)
    return env


def run_probe(wheel_root: Path, statements: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute every documented import in a process whose ``edgeproc_core`` is the wheel."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", PROBE.format(statements="\n".join(statements)), str(wheel_root)],
        cwd=wheel_root.parent,
        env=_probe_env(wheel_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _report(wheel: str, statements: list[str], probe: subprocess.CompletedProcess[str]) -> int:
    """Print the verdict and return the exit code the gate should take."""
    print(f"checked {len(statements)} documented imports against {wheel}:")
    for statement in statements:
        print(f"    {statement}")
    if probe.returncode == 0:
        print(f"\nOK: {probe.stdout.strip()}")
        return 0
    print("\nFAIL: a documented import does not resolve inside the built wheel.")
    print("The docs promise a symbol the published artifact does not ship.")
    print(probe.stderr.strip() or probe.stdout.strip())
    return 1


def _too_few(statements: list[str]) -> int:
    """Report a broken extractor rather than passing vacuously."""
    print(
        f"FAIL: found only {len(statements)} documented imports across {DOCS}; "
        f"expected at least {MIN_EXPECTED_IMPORTS}. The extractor is broken, so a "
        f"pass here would prove nothing."
    )
    return 1


def main() -> int:
    """Build the wheel, unpack it, and probe every documented import against it."""
    statements = documented_imports()
    if len(statements) < MIN_EXPECTED_IMPORTS:
        return _too_few(statements)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wheel = build_wheel(root / "dist")
        probe = run_probe(unpack(wheel, root / "unpacked"), statements)
        return _report(wheel.name, statements, probe)


if __name__ == "__main__":
    sys.exit(main())
