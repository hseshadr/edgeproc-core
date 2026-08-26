"""Release-contract checks for the docs: install paths, provenance, and claims.

The most important check here is
`test_documented_install_refs_actually_ship_the_import_package`. An earlier
version of this file asserted that the README contained a specific install
*string*. That is a spelling check, not a contract: the string it pinned
(`shared-libs-python.git@v0.2.0`) installed the pre-rename `shared_libs_python`
package, so every documented `import edgeproc_core` example raised
`ModuleNotFoundError` — and the guard certified the break instead of catching
it. The check now resolves each documented ref against Git and asserts the tree
at that ref really contains the import package the docs tell you to import.
"""

import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPORT_PACKAGE = "edgeproc_core"
#: The canonical GitHub slug. The repository was renamed `shared-libs-python` ->
#: `edgeproc-core`; GitHub still redirects the old slug, which is exactly why a
#: stale URL can sit in the docs for months without anyone noticing a 404.
#: Pinning the canonical name here makes every documented URL fail loudly instead.
REPO_SLUG = "edgeproc-core"

#: Docs that carry user-facing install commands.
INSTALL_DOCS = ("README.md", "docs/installation-guide.md")

#: A ref is "pinned" if it cannot move under an installer: a full commit SHA or
#: a version tag. Moving refs (`main`) are development-only and excluded here;
#: `test_moving_ref_is_labelled_development_only` covers those instead.
_PINNED_REF = re.compile(r"^(?:[0-9a-f]{40}|v\d+\.\d+\.\d+)$")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _git(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


#: Why a documented install ref fails the contract. These are constants because the
#: tests below assert the exact reason a reader is handed: naming the wrong cause is
#: itself the defect this guard was repaired for.
REF_MISSING = (
    "does not resolve to a commit in this repository. A documented ref must exist "
    "before it is published."
)
REF_LACKS_PACKAGE = (
    f"does not contain the {IMPORT_PACKAGE}/ package, so `pip install ...@<ref>` "
    f"followed by `import {IMPORT_PACKAGE}` raises ModuleNotFoundError. Point the "
    f"docs at a ref whose tree actually ships {IMPORT_PACKAGE}/."
)
SHALLOW_CHECKOUT = (
    "This checkout is SHALLOW, so Git cannot tell a ref that does not exist from one "
    "this clone never fetched: `git rev-parse` fails identically for both. The install "
    "contract is unverifiable here, not proven broken. Add `fetch-depth: 0` to the "
    "actions/checkout step of the workflow running this gate (locally: "
    "`git fetch --unshallow`)."
)


def _is_shallow(root: Path) -> bool:
    """Whether the clone at ``root`` is missing the history it would be judging."""
    return _git("rev-parse", "--is-shallow-repository", cwd=root).stdout.strip() == "true"


def _ref_defects(root: Path, ref: str) -> list[str]:
    """Every way ``ref`` breaks the install contract inside the clone at ``root``."""
    if _git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=root).returncode != 0:
        return [f"Documented install ref {ref!r} {REF_MISSING}"]
    if not _git("ls-tree", "--name-only", ref, f"{IMPORT_PACKAGE}/", cwd=root).stdout.strip():
        return [f"Documented install ref {ref!r} {REF_LACKS_PACKAGE}"]
    return []


def _install_ref_defects(root: Path, refs: Iterable[str]) -> list[str]:
    """Audit ``refs`` against the clone at ``root``, refusing to guess when blind.

    A shallow clone holds only the commit it checked out, so `git rev-parse` on any
    other SHA exits non-zero whether that ref is absent from the *project* or merely
    absent from this *clone*. Reporting "the ref does not exist" there asserts
    something the checkout cannot know — the failure that made the `v0.2.2` publish
    red while the SHA it named was sitting in `main` all along. A check that cannot
    tell fails closed on its own terms instead.
    """
    if _is_shallow(root):
        return [SHALLOW_CHECKOUT]
    return [defect for ref in sorted(refs) for defect in _ref_defects(root, ref)]


def _documented_install_refs() -> set[str]:
    """Every ref the docs tell a user to install from."""
    pattern = re.compile(rf"{re.escape(REPO_SLUG)}\.git@([0-9a-zA-Z._-]+)")
    return {ref for doc in INSTALL_DOCS for ref in pattern.findall(_read(doc))}


def _pinned_install_refs() -> set[str]:
    return {ref for ref in _documented_install_refs() if _PINNED_REF.match(ref)}


def _unpack_ref(ref: str, destination: Path) -> Path:
    """Materialize an immutable documented ref without using the network."""
    archive = destination / "source.tar"
    result = subprocess.run(  # noqa: S603
        ["git", "archive", "--format=tar", "-o", str(archive), ref],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    source = destination / "source"
    shutil.unpack_archive(archive, source, filter="data")
    return source


def _install_ref(source: Path, site: Path) -> None:
    """Build and install a documented source tree into an isolated target."""
    result = subprocess.run(  # noqa: S603
        ["uv", "pip", "install", "--no-deps", "--target", str(site), str(source)],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


_PIN_ISOLATION_PROBE = """
import asyncio
import os
from pathlib import Path

import edgeproc_core
from edgeproc_core import BucketedPartitionStrategy, IndexManager, VectorEmbedding
from edgeproc_core.vector_mgmt.testing import in_memory_factory


async def verify():
    site = Path(os.environ["PIN_SITE"]).resolve()
    assert Path(edgeproc_core.__file__).resolve().is_relative_to(site)
    strategy = BucketedPartitionStrategy(index_factory=in_memory_factory, num_buckets=1)
    manager = IndexManager(strategy)
    await manager.insert([
        VectorEmbedding(entity_id="a", embedding=[1.0, 0.0], metadata={"tenant_id": "a"}),
        VectorEmbedding(entity_id="b", embedding=[1.0, 0.0], metadata={"tenant_id": "b"}),
    ])
    assert strategy.get_search_partitions("a") == strategy.get_search_partitions("b")
    assert [item for item, _ in await manager.search([1.0, 0.0], 10, partition_key="a")] == ["a"]
    stats = await manager.get_stats(partition_key="a")
    await manager.delete(["a", "b"], partition_key="a")
    remaining = await manager.search([1.0, 0.0], 10, partition_key="b")
    observed = (sum(item.vector_count for item in stats), [item for item, _ in remaining])
    assert observed == (1, ["b"]), "scoped stats or delete crossed the collision"


asyncio.run(verify())
"""


def _run_isolation_probe(site: Path, run_dir: Path) -> subprocess.CompletedProcess[str]:
    """Exercise the installed pin from outside both source trees."""
    environment = {"PIN_SITE": str(site), "PYTHONPATH": str(site)}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PIN_ISOLATION_PROBE],
        cwd=run_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def git_repo_available() -> bool:
    """Fail closed when Git-backed release contracts cannot inspect history."""
    if not (ROOT / ".git").exists() or _git("rev-parse", "--git-dir").returncode != 0:
        pytest.fail("not a git checkout; cannot resolve documented refs")
    return True


#: Public surfaces a cold reader arriving from PyPI or GitHub actually lands on.
#: `CHANGELOG.md` is deliberately absent: its released sections are immutable
#: history (see `test_changelog_provenance.py`) and legitimately record the old
#: name. Its *footer links* are checked by
#: `test_changelog_links_continue_from_the_current_release` instead.
PUBLIC_SURFACES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "docs/installation-guide.md",
    "docs/OPERATIONS.md",
    "docs/vector-mgmt-architecture.md",
    "examples/README.md",
)

#: The pre-rename GitHub slug. GitHub redirects it, so a stale link never 404s —
#: it just quietly shows a cold reader the wrong project name.
STALE_REPO_SLUG = "shared-libs-python"


def _stale_slug_lines(doc: str) -> list[str]:
    """Lines of `doc` that still name the pre-rename repository or its clone dir."""
    markers = (f"hseshadr/{STALE_REPO_SLUG}", f"cd {STALE_REPO_SLUG}")
    return [line for line in _read(doc).splitlines() if any(m in line for m in markers)]


def test_no_public_surface_carries_the_pre_rename_repo_slug() -> None:
    """The package is `edgeproc-core`; no public surface may still say otherwise.

    A regression guard, not a spelling check: because GitHub redirects the old
    slug, a stale link never 404s. The only symptom is the wrong identity.
    """
    offenders = {doc: _stale_slug_lines(doc) for doc in PUBLIC_SURFACES}
    offenders = {doc: lines for doc, lines in offenders.items() if lines}

    assert not offenders, (
        f"Public surfaces still carry the pre-rename slug {STALE_REPO_SLUG!r}: "
        f"{offenders}. The canonical repository is "
        f"https://github.com/hseshadr/{REPO_SLUG}."
    )


def test_package_metadata_urls_point_at_the_canonical_repository() -> None:
    """`[project.urls]` is what PyPI renders in the sidebar — it must be canonical."""
    urls = tomllib.loads(_read("pyproject.toml"))["project"]["urls"]

    assert urls, "pyproject declares no [project.urls]; PyPI would show no links at all"
    for label, url in urls.items():
        assert f"github.com/hseshadr/{REPO_SLUG}" in url, (
            f"[project.urls] {label} = {url!r} does not point at the canonical "
            f"repository https://github.com/hseshadr/{REPO_SLUG}."
        )


def test_docs_document_at_least_one_install_ref() -> None:
    """Guard the guard: if the regex stops matching, the checks below go vacuous."""
    assert _pinned_install_refs(), (
        f"No pinned install ref found in {INSTALL_DOCS}. Either the docs lost their "
        f"install command or the extraction pattern needs updating."
    )


def test_documented_install_refs_actually_ship_the_import_package(
    git_repo_available: bool,
) -> None:
    """Installing any documented ref must yield a working `import edgeproc_core`.

    This is the check that would have caught the `v0.2.0` breakage: that tag
    resolves fine and installs fine, but its tree holds `shared_libs_python`,
    so the README's own examples fail at import time.
    """
    assert _install_ref_defects(ROOT, _pinned_install_refs()) == []


@pytest.mark.parametrize("ref", sorted(_pinned_install_refs()))
def test_should_pin_a_supported_release_when_docs_install_source(
    ref: str,
    tmp_path: Path,
) -> None:
    """A source pin that imports but reports an unsupported line is still unsafe."""
    # Given
    source = _unpack_ref(ref, tmp_path)

    # When
    version = str(tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"])
    major, minor, _patch = version.split(".")
    current = str(tomllib.loads(_read("pyproject.toml"))["project"]["version"])

    # Then
    assert version == current, (
        f"Documented source ref {ref} reports {version}, not current release {current}."
    )
    assert f"| >={major}.{minor}.{_patch}" in _read("SECURITY.md"), (
        f"Documented source ref {ref} reports {version}, outside SECURITY.md's supported line."
    )


@pytest.mark.parametrize("ref", sorted(_pinned_install_refs()))
def test_should_preserve_partition_isolation_when_documented_source_pin_is_installed(
    ref: str,
    tmp_path: Path,
) -> None:
    """Import success is insufficient: the installed pin must preserve scoped data."""
    # Given
    source = _unpack_ref(ref, tmp_path)
    site, run_dir = tmp_path / "site", tmp_path / "run"
    run_dir.mkdir()
    _install_ref(source, site)

    # When
    result = _run_isolation_probe(site, run_dir)

    # Then
    assert result.returncode == 0, result.stderr


#: The pre-rename import package, as it sat in the tree before `v0.2.1`.
STALE_IMPORT_PACKAGE = STALE_REPO_SLUG.replace("-", "_")

#: Git flags that ignore the developer's global config, so a fixture repository is
#: built identically on a laptop with signing enabled and on a bare CI runner.
_HERMETIC = (
    "-c",
    "user.name=Fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


def _run_git(cwd: Path, *args: str) -> None:
    """Run a repo-building git command, raising on failure — a fixture must not lie."""
    subprocess.run(  # noqa: S603
        ["git", *_HERMETIC, *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _commit(root: Path, message: str) -> str:
    """Commit everything in ``root`` and return the resulting SHA."""
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-m", message)
    return _git("rev-parse", "HEAD", cwd=root).stdout.strip()


class _History(NamedTuple):
    """A source repository whose two commits straddle the package rename."""

    source: Path
    before_rename: str
    after_rename: str


@pytest.fixture
def history(tmp_path: Path) -> _History:
    """A real two-commit repo: commit one predates the rename, commit two ships it."""
    source = tmp_path / "source"
    (source / STALE_IMPORT_PACKAGE).mkdir(parents=True)
    (source / STALE_IMPORT_PACKAGE / "__init__.py").write_text("", encoding="utf-8")
    _run_git(tmp_path, "init", "-b", "main", str(source))
    before = _commit(source, "the tree before the rename")

    (source / STALE_IMPORT_PACKAGE / "__init__.py").unlink()
    (source / STALE_IMPORT_PACKAGE).rmdir()
    (source / IMPORT_PACKAGE).mkdir()
    (source / IMPORT_PACKAGE / "__init__.py").write_text("", encoding="utf-8")

    return _History(source, before, _commit(source, "rename to the current package"))


def _clone(into: Path, source: Path, name: str, *flags: str) -> Path:
    """Clone ``source`` into ``into/name``. `file://` because `--depth` needs a URL."""
    _run_git(into, "clone", *flags, f"file://{source}", name)
    return into / name


def test_a_shallow_clone_reports_shallowness_not_a_missing_ref(
    tmp_path: Path, history: _History
) -> None:
    """The `v0.2.2` publish failure, reproduced: the ref exists; the clone cannot see it.

    `publish.yml` checked out at depth 1, so the gate declared the README's pinned
    SHA absent from a repository that has always contained it. Naming the wrong
    cause sent a release chasing a docs bug that did not exist.
    """
    shallow = _clone(tmp_path, history.source, "shallow", "--depth", "1")

    defects = _install_ref_defects(shallow, {history.before_rename})

    assert defects == [SHALLOW_CHECKOUT]
    assert REF_MISSING not in "".join(defects), (
        "a shallow clone must not accuse the docs of pinning a ref that does exist"
    )


def test_a_ref_genuinely_absent_from_a_full_clone_still_fails(
    tmp_path: Path, history: _History
) -> None:
    """The original property survives: full history, real verdict."""
    full = _clone(tmp_path, history.source, "full")
    absent = "0" * 40

    assert _install_ref_defects(full, {absent}) == [
        f"Documented install ref {absent!r} {REF_MISSING}"
    ]


def test_a_ref_whose_tree_predates_the_rename_still_fails(
    tmp_path: Path, history: _History
) -> None:
    """The `v0.2.0` defect: the ref resolves, installs, and then cannot be imported."""
    full = _clone(tmp_path, history.source, "full")
    stale = history.before_rename

    assert _install_ref_defects(full, {stale}) == [
        f"Documented install ref {stale!r} {REF_LACKS_PACKAGE}"
    ]


def test_a_ref_that_ships_the_import_package_is_accepted(tmp_path: Path, history: _History) -> None:
    """Guard the opposite direction: a correct pin in a full clone must pass."""
    full = _clone(tmp_path, history.source, "full")

    assert _install_ref_defects(full, {history.after_rename}) == []


def test_moving_ref_is_labelled_development_only() -> None:
    """`@main` may appear, but never as the recommended path for applications."""
    guide = _read("docs/installation-guide.md")
    if f"{REPO_SLUG}.git@main" not in guide:
        return
    assert "development-only" in guide or "Development installs" in guide, (
        "The docs install from the moving `main` ref without marking that path "
        "development-only. Applications must be told to pin."
    )


def test_readme_and_guide_agree_on_the_pinned_ref() -> None:
    """One pin, documented once, in both places — so they cannot drift apart."""
    readme_refs = {
        ref
        for ref in re.findall(rf"{re.escape(REPO_SLUG)}\.git@([0-9a-f]{{40}})", _read("README.md"))
    }
    guide_refs = {
        ref
        for ref in re.findall(
            rf"{re.escape(REPO_SLUG)}\.git@([0-9a-f]{{40}})",
            _read("docs/installation-guide.md"),
        )
    }
    assert readme_refs == guide_refs, (
        f"README pins {readme_refs or '{}'} but the installation guide pins "
        f"{guide_refs or '{}'}. A reader following either must get the same code."
    )


def test_docs_do_not_advertise_a_release_artifact_that_does_not_exist() -> None:
    """No doc may link a GitHub Release wheel until a release actually publishes one.

    The README once linked `edgeproc_core-0.2.0-py3-none-any.whl`, which 404s:
    the `v0.2.0` release predates the rename and its asset is named
    `shared_libs_python-0.2.0-py3-none-any.whl`.
    """
    for doc in INSTALL_DOCS:
        assert "/releases/download/" not in _read(doc), (
            f"{doc} links a GitHub Release download URL. Release assets are only "
            f"linkable once the corresponding release exists and carries that "
            f"exact filename; verify with curl before documenting one."
        )


def test_security_policy_supports_the_current_release_line() -> None:
    """SECURITY.md must name the current supported floor — derived, not frozen.

    This asserted the literal `| 0.2.x` while the package shipped `0.3.0`. It
    pinned a spelling instead of the contract, so it went on passing as the
    policy went stale: readers were told the supported line was two minors
    behind the only version on PyPI. Deriving the expected line from
    `pyproject.toml` means the two files can only ever agree.
    """
    version = str(tomllib.loads(_read("pyproject.toml"))["project"]["version"])
    security = _read("SECURITY.md")

    assert f"| >={version}" in security, (
        f"pyproject publishes {version} but SECURITY.md does not support that release floor."
    )
    assert f"| <{version}" in security, "Superseded releases are not marked unsupported."


@pytest.mark.parametrize(
    "heading",
    [
        "## Threat model and trust boundaries",
        "## Privacy and data flow",
        "## Reliability and recovery contract",
        "## Measured performance contract",
    ],
)
def test_operations_contract_documents_its_required_sections(heading: str) -> None:
    assert heading in _read("docs/OPERATIONS.md")


def test_readme_links_the_operations_contract() -> None:
    assert "docs/OPERATIONS.md" in _read("README.md")


def test_readme_status_matches_package_version() -> None:
    version = tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    assert f"This source and packaged README describe v{version}" in _read("README.md")


def test_should_describe_the_packaged_release_without_a_stale_registry_claim() -> None:
    """The immutable description must identify itself, not snapshot registry state."""
    # Given
    version = tomllib.loads(_read("pyproject.toml"))["project"]["version"]

    # When
    readme = _read("README.md")

    # Then
    assert f"This source and packaged README describe v{version}" in readme
    assert f'"edgeproc-core=={version}"' in readme
    assert f"# {version}" in readme
    assert "PyPI currently serves" not in readme
    assert f"## [{version}]" in _read("CHANGELOG.md")


def test_readme_leads_with_a_copy_paste_demo_before_evidence() -> None:
    readme = _read("README.md")
    quickstart = readme.index("## Quickstart")

    assert quickstart < readme.index("## Measured evidence")
    assert "bash examples/run_loop.sh" in readme[quickstart : readme.index("## Measured evidence")]


def test_readme_states_the_python_requirement_before_installing() -> None:
    """A cold reader on 3.12 must learn why the install fails before they run it."""
    readme = _read("README.md")
    requires = tomllib.loads(_read("pyproject.toml"))["project"]["requires-python"]
    minimum = requires.lstrip(">=~^ ")

    assert f"Python {minimum}" in readme, (
        f"README never states the Python {minimum} requirement; `pip install` on an "
        f"older interpreter fails with an unhelpful resolver error."
    )
    assert readme.index(f"Python {minimum}") < readme.index("uv pip install"), (
        "The Python requirement must appear before the first install command."
    )


def _released_versions_newest_first() -> list[str]:
    """Every released version in CHANGELOG.md, in the order the file lists them."""
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", _read("CHANGELOG.md"), flags=re.M)


def test_changelog_links_continue_from_the_current_release() -> None:
    """The compare link must span the ACTUAL previous release, not a fixed one.

    This assertion used to hardcode `compare/v0.2.0...v{version}`. That was right
    at 0.2.1 by coincidence and wrong for every release after it: cutting 0.2.2
    forced a link claiming 0.2.2 diverged from 0.2.0, writing 0.2.1 out of the
    range the link renders on GitHub. The predecessor is now read from the
    changelog's own ordering, so the guard tracks the release history instead of
    a constant that only ever agreed with it once.
    """
    version = tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    changelog = _read("CHANGELOG.md")
    repository = f"https://github.com/hseshadr/{REPO_SLUG}"
    released = _released_versions_newest_first()

    assert released[:1] == [version], (
        f"CHANGELOG's newest released section is {released[:1]}, but pyproject "
        f"declares {version}. Cut the section before tagging."
    )
    previous = released[1]
    assert f"[Unreleased]: {repository}/compare/v{version}...HEAD" in changelog
    assert f"[{version}]: {repository}/compare/v{previous}...v{version}" in changelog


def test_every_released_section_carries_a_link_reference() -> None:
    """Non-vacuity for the check above: the parse must really see the history."""
    released = _released_versions_newest_first()
    assert len(released) >= 2, f"changelog parse found {len(released)} releases"
    changelog = _read("CHANGELOG.md")
    prefix = f"https://github.com/hseshadr/{REPO_SLUG}/"
    missing = [v for v in released if f"[{v}]: {prefix}" not in changelog]
    assert not missing, f"released sections with no link reference: {missing}"


def test_the_gate_measures_branch_coverage_not_just_statements() -> None:
    """The README publishes a *branch* figure, so the gate must measure branches.

    `--cov-branch` was once absent, which made the published "98.62% branch
    coverage" really statement coverage. This pins the stricter measurement in
    place so the claim and the gate cannot drift apart again.
    """
    pytest_config = tomllib.loads(_read("pyproject.toml"))["tool"]["pytest"]["ini_options"]

    assert "--cov-branch" in pytest_config["addopts"]


def test_published_coverage_floor_matches_the_configured_floor() -> None:
    """The floor the docs promise is the floor the gate actually enforces."""
    config = tomllib.loads(_read("pyproject.toml"))
    configured = config["tool"]["coverage"]["report"]["fail_under"]
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]

    assert f"--cov-fail-under={configured:.0f}" in addopts
    assert f"≥{configured:.0f}% branch coverage" in _read("README.md")
