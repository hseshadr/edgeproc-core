"""Behavioral contracts for EdgeProc Core's composed Dagger release graph."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import cast

import dagger
import pytest

from edgeproc_core import main
from edgeproc_core.main import EdgeprocCore

ROOT = Path(__file__).parents[2]
COMMIT_SHA = "a" * 40
EXPECTED_CENTRAL_SHA = "95c72573fc11ea6732abb7f7fe8b59c7d245d927"


class RecordingWorkspace:
    """Record the explicit source directory selected by the constructor."""

    def __init__(self) -> None:
        self.path = ""

    def directory(self, path: str, **_options: object) -> dagger.Directory:
        self.path = path
        return cast(dagger.Directory, object())


class RecordingContainer:
    """Record when one lazy Dagger security or audit graph is evaluated."""

    def __init__(self) -> None:
        self.synced = False

    async def sync(self) -> RecordingContainer:
        self.synced = True
        return self


class RecordingDirectory:
    """Record the exact Git metadata overlay applied to one bound snapshot."""

    def __init__(self, guard: RecordingContainer) -> None:
        self.guard = guard
        self.includes: list[str] = []
        self.overlay: tuple[str, object] | None = None
        self.guard_synced_when_filtered = False

    def filter(self, *, include: list[str]) -> RecordingDirectory:
        self.includes = include
        self.guard_synced_when_filtered = self.guard.synced
        return self

    def with_directory(self, path: str, directory: object) -> RecordingDirectory:
        self.overlay = (path, directory)
        return self


class RecordingFoundation:
    """Record exact Foundation source and guard identities."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str, str]] = []
        self.bound = cast(dagger.Directory, object())
        self.security = RecordingContainer()

    def source(
        self, source: dagger.Directory, repository: str, commit_sha: str
    ) -> dagger.Directory:
        self.calls.append(("source", source, repository, commit_sha))
        return self.bound

    def guard(self, source: dagger.Directory, repository: str, commit_sha: str) -> dagger.Container:
        self.calls.append(("guard", source, repository, commit_sha))
        return cast(dagger.Container, self.security)


class RecordingCandidate:
    """Expose one verified envelope in the generated candidate shape."""

    def __init__(self, envelope: dagger.Directory) -> None:
        self._envelope = envelope

    def envelope(self) -> dagger.Directory:
        return self._envelope


class RecordingArtifactEnvelope:
    """Record projection of one authenticated Foundation artifact subtree."""

    def __init__(self) -> None:
        self.artifact = cast(dagger.Directory, object())
        self.requested: list[str] = []

    def directory(self, path: str) -> dagger.Directory:
        self.requested.append(path)
        return self.artifact


class RecordingPythonPackage:
    """Record the closed reusable package operations selected by the adapter."""

    def __init__(self) -> None:
        self.audit = RecordingContainer()
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.created = cast(dagger.Directory, object())
        self.verified = cast(dagger.Directory, object())

    def dependency_audit(
        self, source: dagger.Directory, repository: str, commit_sha: str
    ) -> dagger.Container:
        self.calls.append(("dependency_audit", (source, repository, commit_sha)))
        return cast(dagger.Container, self.audit)

    def candidate(self, *arguments: object) -> RecordingCandidate:
        self.calls.append(("candidate", arguments))
        return RecordingCandidate(self.created)

    def verify_candidate(self, *arguments: object) -> RecordingCandidate:
        self.calls.append(("verify_candidate", arguments))
        return RecordingCandidate(self.verified)


def test_should_select_explicit_root_when_constructing_release_graph() -> None:
    # Given
    workspace = RecordingWorkspace()

    # When
    EdgeprocCore.create(cast(dagger.Workspace, workspace))

    # Then
    assert workspace.path == "/"


def test_should_require_typed_workspace_when_constructing_release_graph() -> None:
    # Given
    signature = inspect.signature(EdgeprocCore.create, eval_str=True)

    # When
    workspace = signature.parameters.get("workspace")

    # Then
    assert workspace is not None
    assert workspace.annotation is dagger.Workspace


def test_should_expose_only_composed_quality_and_release_boundaries() -> None:
    # Given
    expected = {"ci", "quality", "dependency_audit", "release_candidate"}

    # When
    available = {name for name in expected if hasattr(EdgeprocCore, name)}

    # Then
    assert available == expected
    assert not hasattr(EdgeprocCore, "secret_scan")
    assert not hasattr(EdgeprocCore, "workflow_security")


def test_should_require_bound_sha_for_every_unprivileged_entrypoint() -> None:
    # Given / When
    names = ("ci", "quality", "dependency_audit")
    signatures = [inspect.signature(getattr(EdgeprocCore, name), eval_str=True) for name in names]

    # Then
    assert all(
        item.parameters["commit_sha"].default is inspect.Parameter.empty for item in signatures
    )


def test_should_bind_snapshot_before_product_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    foundation = RecordingFoundation()
    history = RecordingDirectory(foundation.security)
    requested_history: list[str] = []
    source = cast(dagger.Directory, object())
    monkeypatch.setattr(main, "_foundation", lambda: foundation)
    monkeypatch.setattr(
        main,
        "_history",
        lambda commit_sha: requested_history.append(commit_sha) or history,
    )

    # When
    actual = asyncio.run(EdgeprocCore._verified_source(source, COMMIT_SHA))

    # Then
    assert actual is history
    assert foundation.security.synced
    assert requested_history == [COMMIT_SHA]
    assert history.guard_synced_when_filtered
    assert history.includes == [".git", ".git/**"]
    assert history.overlay == ("/", foundation.bound)
    assert foundation.calls == [
        ("source", source, "hseshadr/edgeproc-core", COMMIT_SHA),
        ("guard", source, "hseshadr/edgeproc-core", COMMIT_SHA),
    ]


def test_should_delegate_dependency_audit_to_shared_python_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    package = RecordingPythonPackage()
    source = cast(dagger.Directory, object())
    graph = EdgeprocCore.__new__(EdgeprocCore)
    graph.source = source
    monkeypatch.setattr(main, "_python_package", lambda: package)

    # When
    actual = graph.dependency_audit(COMMIT_SHA)

    # Then
    assert actual is package.audit
    assert package.calls == [("dependency_audit", (source, "hseshadr/edgeproc-core", COMMIT_SHA))]


def test_should_create_then_verify_closed_candidate_with_same_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    package = RecordingPythonPackage()
    source = cast(dagger.Directory, object())
    token = cast(dagger.Secret, object())
    monkeypatch.setattr(main, "_python_package", lambda: package)

    # When
    actual = EdgeprocCore._candidate_envelope(source, token, COMMIT_SHA, "6100", 2)

    # Then
    identity = (
        source,
        token,
        "hseshadr/edgeproc-core",
        COMMIT_SHA,
        "edgeproc-core",
        EXPECTED_CENTRAL_SHA,
        "6100",
        2,
    )
    assert package.calls == [
        ("candidate", identity),
        ("verify_candidate", (package.created, *identity[2:])),
    ]
    assert actual is package.verified


def test_should_project_authenticated_artifact_into_existing_publisher_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    graph = EdgeprocCore.__new__(EdgeprocCore)
    graph.source = cast(dagger.Directory, object())
    envelope = RecordingArtifactEnvelope()
    checked_tags: list[str] = []

    async def verified(source: dagger.Directory, _commit_sha: str) -> dagger.Directory:
        return source

    async def product_gate(_graph: EdgeprocCore, _source: dagger.Directory) -> None:
        return None

    async def green_identity(_token: dagger.Secret) -> tuple[str, int]:
        return "6100", 2

    monkeypatch.setattr(EdgeprocCore, "_verified_source", staticmethod(verified))
    monkeypatch.setattr(EdgeprocCore, "_run_product_gate", product_gate)
    monkeypatch.setattr(EdgeprocCore, "_green_identity", staticmethod(green_identity))
    monkeypatch.setattr(
        EdgeprocCore,
        "_candidate_envelope",
        staticmethod(lambda *_arguments: cast(dagger.Directory, envelope)),
    )
    monkeypatch.setattr(
        EdgeprocCore,
        "_require_requested_tag",
        staticmethod(lambda value, tag: checked_tags.append(tag) or value),
    )

    # When
    actual = asyncio.run(
        graph.release_candidate("v0.4.2", COMMIT_SHA, cast(dagger.Secret, object()))
    )

    # Then
    assert checked_tags == ["v0.4.2"]
    assert envelope.requested == ["artifact"]
    assert actual is envelope.artifact


def test_should_pin_both_shared_modules_to_same_reviewed_commit() -> None:
    # Given / When
    config = json.loads((ROOT / "dagger.json").read_text(encoding="utf-8"))
    dependencies = {item["name"]: item for item in config["dependencies"]}

    # Then
    assert set(dependencies) == {"foundation", "python-package"}
    assert main.CENTRAL_MODULE_SHA == EXPECTED_CENTRAL_SHA
    assert {item["pin"] for item in dependencies.values()} == {EXPECTED_CENTRAL_SHA}
    assert dependencies["foundation"]["source"].endswith(
        f"/modules/portfolio-foundation@{EXPECTED_CENTRAL_SHA}"
    )
    assert dependencies["python-package"]["source"].endswith(
        f"/modules/python-package@{EXPECTED_CENTRAL_SHA}"
    )


def test_should_require_typed_secret_for_hosted_release_eligibility() -> None:
    # Given
    signature = inspect.signature(EdgeprocCore.release_candidate, eval_str=True)

    # When
    token = signature.parameters.get("github_token")
    result = signature.return_annotation

    # Then
    assert token is not None
    assert token.annotation is dagger.Secret
    assert result is dagger.Directory
