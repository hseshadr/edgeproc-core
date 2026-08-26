"""Executable contracts for thin Dagger ingress and source-free PyPI OIDC."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
DAGGER_ACTION = "dagger/dagger-for-github"
CHECKOUT_ACTION = "actions/checkout"


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {"on" if key is True else str(key): item for key, item in value.items()}


def _workflow(name: str) -> dict[str, object]:
    path = WORKFLOWS / name
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def _job(document: Mapping[str, object], name: str) -> dict[str, object]:
    return _mapping(_mapping(document.get("jobs")).get(name))


def _steps(job: Mapping[str, object]) -> list[dict[str, object]]:
    steps = job.get("steps")
    return [_mapping(step) for step in steps] if isinstance(steps, list) else []


def _action(step: Mapping[str, object]) -> str:
    uses = step.get("uses")
    return str(uses).split("@")[0] if isinstance(uses, str) else ""


def _workflow_files(directory: Path) -> list[Path]:
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def _external_actions(directory: Path) -> list[str]:
    uses = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
    return [
        action
        for path in _workflow_files(directory)
        for action in uses.findall(path.read_text(encoding="utf-8"))
        if not action.startswith("./")
    ]


def _assert_thin_dagger(job: Mapping[str, object], args: str) -> None:
    steps = _steps(job)
    assert [_action(step) for step in steps] == [CHECKOUT_ACTION, DAGGER_ACTION]
    assert all(PINNED.fullmatch(str(step.get("uses"))) for step in steps)
    checkout = _mapping(steps[0].get("with"))
    invocation = _mapping(steps[1].get("with"))
    assert checkout.get("fetch-depth") == 0
    assert checkout.get("persist-credentials") is False
    assert invocation == {"version": "0.21.8", "verb": "call", "args": args}


def test_should_pin_every_external_action_in_yml_and_yaml() -> None:
    actions = _external_actions(WORKFLOWS)
    assert actions
    assert [action for action in actions if PINNED.fullmatch(action) is None] == []


def test_should_fail_pin_audit_for_a_yaml_bypass(tmp_path: Path) -> None:
    (tmp_path / "bypass.yaml").write_text(
        "jobs:\n  bypass:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    assert _external_actions(tmp_path) == ["actions/checkout@v4"]


def test_should_route_shadow_ci_through_dagger_without_replacing_legacy_gate() -> None:
    document = _workflow("dagger-shadow.yml")
    job = _job(document, "dagger-shadow")
    _assert_thin_dagger(job, "ci --commit-sha=${{ github.sha }}")
    assert job.get("name") == "Dagger shadow"
    assert (WORKFLOWS / "ci.yml").is_file()
