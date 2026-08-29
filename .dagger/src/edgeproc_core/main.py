"""EdgeProc Core's composed quality, security, and candidate graph."""

from __future__ import annotations

from typing import Final, Self

import dagger
from dagger import check, dag, field, function, object_type

PYTHON_IMAGE: Final = (
    "python:3.13.14-slim@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6"
)
UV_IMAGE: Final = (
    "ghcr.io/astral-sh/uv:0.11.32@sha256:"
    "df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c"
)
GIT_PACKAGE: Final = "git=1:2.47.3-0+deb13u1"
REPOSITORY: Final = "hseshadr/edgeproc-core"
REPOSITORY_URL: Final = f"https://github.com/{REPOSITORY}.git"
PROJECT_NAME: Final = "edgeproc-core"
CENTRAL_MODULE_SHA: Final = "95c72573fc11ea6732abb7f7fe8b59c7d245d927"
SOURCE_EXCLUDES: Final = [
    ".git",
    ".venv",
    ".dagger/.venv",
    ".dagger/sdk",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "**/__pycache__",
    "dist",
]
CANDIDATE_TAG_CHECK: Final = """
import json
import os
from pathlib import Path

manifest = Path('/candidate/artifact/metadata/python-candidate.json')
actual = json.loads(manifest.read_text(encoding='utf-8'))['tag']
if actual != os.environ['EXPECTED_TAG']:
    raise SystemExit('requested tag differs from the verified candidate')
"""
WORK_DIRECTORIES: Final = ["mkdir", "-p", "/opt/venv", "/opt/home", "/opt/model-cache", "/opt/tmp"]
OWNERSHIP_COMMAND: Final = [
    "chown",
    "-R",
    "65532:65532",
    "/opt/venv",
    "/opt/home",
    "/opt/model-cache",
    "/opt/tmp",
]


def _foundation() -> dagger.Foundation:
    """Return the exact-SHA generated Foundation dependency."""
    return dag.foundation()


def _python_package() -> dagger.PythonPackage:
    """Return the exact-SHA generated Python package dependency."""
    return dag.python_package()


def _history(commit_sha: str) -> dagger.Directory:
    """Return canonical Git metadata for the already-verified commit."""
    return dag.git(REPOSITORY_URL).commit(commit_sha).tree(depth=0, include_tags=True)


def _with_history(source: dagger.Directory, commit_sha: str) -> dagger.Directory:
    """Overlay the verified caller snapshot onto exact-commit Git metadata."""
    metadata = _history(commit_sha).filter(include=[".git", ".git/**"])
    return metadata.with_directory("/", source)


# fmt: off
def _create_candidate(
    source: dagger.Directory, token: dagger.Secret, commit_sha: str,
    workflow_run_id: str, run_attempt: int,
) -> dagger.PythonPackageCandidate:
    return _python_package().candidate(
        source, token, REPOSITORY, commit_sha, PROJECT_NAME,
        CENTRAL_MODULE_SHA, workflow_run_id, run_attempt,
    )


def _verify_candidate(
    envelope: dagger.Directory, commit_sha: str, workflow_run_id: str, run_attempt: int,
) -> dagger.Directory:
    verified = _python_package().verify_candidate(
        envelope, REPOSITORY, commit_sha, PROJECT_NAME,
        CENTRAL_MODULE_SHA, workflow_run_id, run_attempt,
    )
    return verified.envelope()
# fmt: on


@object_type
class EdgeprocCore:
    """Run the same typed EdgeProc Core release graph locally and on GitHub."""

    source: dagger.Directory = field()

    @classmethod
    def create(cls, workspace: dagger.Workspace) -> Self:
        """Construct the graph from an explicit typed workspace snapshot."""
        instance = cls.__new__(cls)
        instance.source = workspace.directory("/", exclude=SOURCE_EXCLUDES)
        return instance

    @function
    async def quality(self, commit_sha: str) -> dagger.Container:
        """Return product quality after exact source binding and the shared guard."""
        complete = await self._verified_source(self.source, commit_sha)
        return self._quality(complete)

    @function
    def dependency_audit(self, commit_sha: str) -> dagger.Container:
        """Audit the bound frozen graph through the shared Python package Lego."""
        return self._dependency_audit(commit_sha)

    @function
    @check
    async def ci(self, commit_sha: str) -> str:
        """Run the canonical release gate sequentially to bound runner memory."""
        complete = await self._verified_source(self.source, commit_sha)
        await self._run_product_gate(complete)
        await self._dependency_audit(commit_sha).sync()
        return "EdgeProc Core canonical Dagger gate passed"

    def _dependency_audit(self, commit_sha: str) -> dagger.Container:
        return _python_package().dependency_audit(self.source, REPOSITORY, commit_sha)

    # fmt: off
    @function(cache="never")  # type: ignore[call-overload,untyped-decorator]  # SDK stub gap
    async def release_candidate(
        self, tag: str, commit_sha: str, github_token: dagger.Secret,
    ) -> dagger.Directory:
        """Build one exact, verified Foundation envelope without publishing it."""
        complete = await self._verified_source(self.source, commit_sha)
        await self._run_product_gate(complete)
        run_id, attempt = await self._green_identity(github_token)
        envelope = self._candidate_envelope(
            self.source, github_token, commit_sha, run_id, attempt,
        )
        checked = self._require_requested_tag(envelope, tag)
        return checked.directory("artifact")
    # fmt: on

    async def _run_product_gate(self, source: dagger.Directory) -> None:
        tested = self._quality(source).with_exec(["bash", "examples/run_loop.sh"])
        benchmark = tested.with_exec(["uv", "run", "python", "benchmarks/benchmark.py"])
        await benchmark.sync()

    @staticmethod
    async def _verified_source(source: dagger.Directory, commit_sha: str) -> dagger.Directory:
        foundation = _foundation()
        bound = foundation.source(source, REPOSITORY, commit_sha)
        await foundation.guard(source, REPOSITORY, commit_sha).sync()
        return _with_history(bound, commit_sha)

    @staticmethod
    async def _green_identity(token: dagger.Secret) -> tuple[str, int]:
        evidence = _foundation().green_main(token, REPOSITORY)
        run_id = await evidence.workflow_run_id()
        attempt = await evidence.run_attempt()
        return run_id, attempt

    @staticmethod
    def _candidate_envelope(
        source: dagger.Directory,
        token: dagger.Secret,
        commit_sha: str,
        workflow_run_id: str,
        run_attempt: int,
    ) -> dagger.Directory:
        candidate = _create_candidate(source, token, commit_sha, workflow_run_id, run_attempt)
        return _verify_candidate(candidate.envelope(), commit_sha, workflow_run_id, run_attempt)

    @staticmethod
    def _require_requested_tag(envelope: dagger.Directory, tag: str) -> dagger.Directory:
        checked = dag.container().from_(PYTHON_IMAGE).with_directory("/candidate", envelope)
        checked = checked.with_env_variable("EXPECTED_TAG", tag)
        return checked.with_exec(["python", "-c", CANDIDATE_TAG_CHECK]).directory("/candidate")

    def _python(self, source: dagger.Directory) -> dagger.Container:
        configured = self._configured_python(source)
        prepared = self._prepared_python(configured)
        return prepared.with_user("65532:65532").with_exec(
            ["uv", "sync", "--frozen", "--all-extras"]
        )

    def _configured_python(self, source: dagger.Directory) -> dagger.Container:
        base = self._python_toolchain().with_directory("/src", source, owner="65532:65532")
        base = base.with_workdir("/src").with_env_variable("UV_PROJECT_ENVIRONMENT", "/opt/venv")
        base = base.with_env_variable("UV_CACHE_DIR", "/opt/uv-cache")
        base = base.with_env_variable("UV_LINK_MODE", "copy").with_env_variable("HOME", "/opt/home")
        base = base.with_env_variable("XDG_CACHE_HOME", "/opt/model-cache")
        return base.with_env_variable("HF_HOME", "/opt/model-cache/huggingface")

    @staticmethod
    def _prepared_python(base: dagger.Container) -> dagger.Container:
        base = base.with_env_variable("TMPDIR", "/opt/tmp")
        cache = dag.cache_volume("edgeproc-core-uv-nonroot")
        base = base.with_mounted_cache("/opt/uv-cache", cache, owner="65532:65532")
        base = base.with_exec(WORK_DIRECTORIES)
        return base.with_exec(OWNERSHIP_COMMAND)

    def _quality(self, source: dagger.Directory) -> dagger.Container:
        return self._python(source).with_exec(["uv", "run", "poe", "gate"])

    @staticmethod
    def _python_toolchain() -> dagger.Container:
        uv = dag.container().from_(UV_IMAGE).file("/uv")
        install = [
            "sh",
            "-ceu",
            "apt-get update && "
            f"apt-get install -y --no-install-recommends '{GIT_PACKAGE}' && "
            "rm -rf /var/lib/apt/lists/*",
        ]
        base = dag.container().from_(PYTHON_IMAGE).with_exec(install)
        return base.with_file("/usr/local/bin/uv", uv)
