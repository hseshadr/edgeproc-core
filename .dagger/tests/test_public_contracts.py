"""Behavioral contracts for EdgeProc Core's typed Dagger release graph."""

from __future__ import annotations

import inspect
from typing import cast

import dagger
import pytest

from edgeproc_core.main import EdgeprocCore


class RecordingWorkspace:
    """Record the explicit source directory selected by the constructor."""

    def __init__(self) -> None:
        self.path = ""

    def directory(self, path: str, **_options: object) -> dagger.Directory:
        self.path = path
        return cast(dagger.Directory, object())


class RecordingDirectory:
    """Record history filtering and typed-source overlay behavior."""

    def __init__(self) -> None:
        self.includes: list[str] = []
        self.overlay: object | None = None

    def filter(self, *, include: list[str]) -> RecordingDirectory:
        self.includes = include
        return self

    def with_directory(self, _path: str, source: object) -> RecordingDirectory:
        self.overlay = source
        return self


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


def test_should_expose_one_canonical_check_and_release_boundaries() -> None:
    # Given
    expected = {
        "ci",
        "quality",
        "dependency_audit",
        "secret_scan",
        "workflow_security",
        "release_candidate",
    }

    # When
    available = {name for name in expected if hasattr(EdgeprocCore, name)}

    # Then
    assert available == expected


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


def test_should_actionlint_both_github_workflow_extensions() -> None:
    # Given / When
    command = inspect.getsource(EdgeprocCore._workflow_security)

    # Then
    assert "*.yml" in command
    assert "*.yaml" in command


def test_should_take_only_git_metadata_from_remote_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a remote commit with files that may have been deleted in the typed source
    history = RecordingDirectory()
    source = object()
    monkeypatch.setattr(
        EdgeprocCore,
        "_release_source",
        staticmethod(lambda _commit: cast(dagger.Directory, history)),
    )
    graph = EdgeprocCore.__new__(EdgeprocCore)

    # When the exact source is composed with its usable Git history
    result = graph._source_with_history(cast(dagger.Directory, source), "a" * 40)

    # Then no remote working-tree file can survive a typed-source deletion
    assert history.includes == [".git", ".git/**"]
    assert history.overlay is source
    assert result is history
