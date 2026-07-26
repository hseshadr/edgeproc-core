"""GitHub Actions must resolve third-party code from immutable commits.

A moving tag (`@v4`) is a supply-chain hole: whoever controls the tag controls
what runs in CI. Only a full 40-character commit SHA is immutable.

This check globs **both** YAML extensions. It previously matched `*.yml` alone,
so a `deploy.yaml` carrying an unpinned action would have passed without ever
being opened — a green result that proved nothing. The reference count is
asserted non-zero for the same reason: a test that inspects nothing must fail
rather than quietly succeed.

The second half of this module guards the other end of the same supply chain:
**every PyPI release must ship PEP 740 provenance.** Two lines make that true —
`attestations: true` on the publish step, which tells PyPI to store a signed
attestation beside the wheel, and `id-token: write` on the publish job, which
lets the job mint the OIDC token that signs it. Delete either and releases keep
going out green, just silently unsigned; nothing else in this repo would notice.
So the audit below is asserted against the real workflows *and* driven against
synthetic fixtures that break it, including one carrying the literal text
`attestations: true` inside a comment — because a guard that greps for a string
measures the shape of a file, not the property it is supposed to hold.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
YAML_GLOBS = ("*.yml", "*.yaml")
PYPI_PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
NO_ATTESTATIONS = "publish step does not set `with: attestations: true` (PEP 740)"
NO_OIDC = "publish job does not grant `permissions: id-token: write`"


def _workflow_files(directory: Path) -> list[Path]:
    """Every workflow file in ``directory``, under either YAML extension."""
    return sorted(path for glob in YAML_GLOBS for path in directory.glob(glob))


def _unpinned(action: str) -> bool:
    """Whether ``action`` resolves to something other than a full commit SHA."""
    return not action.startswith("./") and PINNED.fullmatch(action) is None


def _audit(directory: Path) -> tuple[list[str], int]:
    """Return ``(failures, references_examined)`` for the workflows in ``directory``."""
    failures: list[str] = []
    examined = 0
    for workflow in _workflow_files(directory):
        for action in USES.findall(workflow.read_text(encoding="utf-8")):
            examined += 1
            if _unpinned(action):
                failures.append(f"{workflow.name}: {action}")
    return failures, examined


def test_external_actions_are_pinned_to_full_commit_shas() -> None:
    """No workflow may reference a third-party action by a moving tag."""
    failures, examined = _audit(WORKFLOWS)

    assert failures == []
    assert examined > 0, "vacuous pass: no `uses:` reference was examined"


def test_the_audit_reports_nothing_examined_for_an_empty_directory(tmp_path: Path) -> None:
    """Non-vacuity proof: with no workflows to read, the count is zero.

    This is what makes the `examined > 0` assertion above meaningful — it shows
    the counter reflects work actually done, so an empty or mis-globbed
    directory cannot masquerade as a clean audit.
    """
    assert _audit(tmp_path) == ([], 0)


@pytest.mark.parametrize("extension", [".yml", ".yaml"])
def test_an_unpinned_action_is_caught_under_either_extension(
    tmp_path: Path, extension: str
) -> None:
    """The original defect: a `.yaml` workflow was never opened."""
    workflow = tmp_path / f"deploy{extension}"
    workflow.write_text("jobs:\n  a:\n    steps:\n      - uses: foo/bar@v4\n")

    failures, examined = _audit(tmp_path)

    assert failures == [f"deploy{extension}: foo/bar@v4"]
    assert examined == 1


def test_a_full_sha_and_a_local_action_both_pass(tmp_path: Path) -> None:
    """Guard the opposite direction: valid references must not be flagged."""
    sha = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    body = f"steps:\n  - uses: a/b@{sha}\n  - uses: ./.github/actions/x\n"
    (tmp_path / "ok.yaml").write_text(body)

    assert _audit(tmp_path) == ([], 2)


class _PublishStep(NamedTuple):
    """One ``pypa/gh-action-pypi-publish`` step, reduced to the facts under audit."""

    where: str
    attested: bool
    oidc: bool


def _as_mapping(value: object) -> dict[str, object]:
    """``value`` as a string-keyed mapping; anything else reads as empty.

    Keys are stringified because YAML 1.1 parses a workflow's ``on:`` into the
    boolean key ``True`` — a lookup assuming plain string keys trips over a real file.
    """
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _job_steps(job: Mapping[str, object]) -> list[dict[str, object]]:
    """The step list of ``job``, normalised to mappings."""
    steps = job.get("steps")
    return [_as_mapping(step) for step in steps] if isinstance(steps, list) else []


def _action_of(step: Mapping[str, object]) -> str:
    """The action a step runs, minus its ``@ref``. Empty for a plain ``run:`` step."""
    uses = step.get("uses")
    return uses.split("@")[0] if isinstance(uses, str) else ""


def _switched_on(value: object) -> bool:
    """Whether an action input is enabled.

    Accepts the YAML boolean and the quoted string alike: GitHub coerces every
    input to a string, so ``attestations: "true"`` enables provenance as ``true`` does.
    """
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _grants_oidc(job: Mapping[str, object]) -> bool:
    """Whether ``job`` explicitly grants the OIDC scope PEP 740 signing needs.

    Explicit only: a blanket ``permissions: write-all`` would also confer it, but
    these workflows are least-privilege by policy, so it is not accepted here.
    """
    return _as_mapping(job.get("permissions")).get("id-token") == "write"


def _publish_steps_of(where: str, job: Mapping[str, object]) -> list[_PublishStep]:
    """The PyPI-publish steps of one job, each carrying that job's OIDC verdict."""
    oidc = _grants_oidc(job)
    return [
        _PublishStep(where, _switched_on(_as_mapping(step.get("with")).get("attestations")), oidc)
        for step in _job_steps(job)
        if _action_of(step) == PYPI_PUBLISH_ACTION
    ]


def _publish_steps_in(workflow: Path) -> list[_PublishStep]:
    """Every PyPI-publish step in one workflow file, across all of its jobs."""
    document = _as_mapping(yaml.safe_load(workflow.read_text(encoding="utf-8")))
    return [
        found
        for name, job in _as_mapping(document.get("jobs")).items()
        for found in _publish_steps_of(f"{workflow.name}:{name}", _as_mapping(job))
    ]


def _provenance_defects(step: _PublishStep) -> list[str]:
    """Every provenance invariant ``step`` breaks, as reader-facing failure lines."""
    broken: list[str] = []
    if not step.attested:
        broken.append(NO_ATTESTATIONS)
    if not step.oidc:
        broken.append(NO_OIDC)
    return [f"{step.where}: {reason}" for reason in broken]


def _audit_provenance(directory: Path) -> tuple[list[str], int]:
    """Return ``(failures, publish_steps_examined)`` for the workflows in ``directory``.

    The step count exists for the same reason the reference count does above: if the
    publish step is renamed or removed, this must go red rather than scan an empty set.
    """
    steps = [found for path in _workflow_files(directory) for found in _publish_steps_in(path)]
    return [defect for step in steps for defect in _provenance_defects(step)], len(steps)


OIDC_GRANTED = "    permissions:\n      id-token: write\n      contents: read\n"
NO_PERMISSIONS = ""
CONTENTS_READ_ONLY = "    permissions:\n      contents: read\n"
ATTESTED = "        with:\n          attestations: true\n"
ATTESTATIONS_OFF = "        with:\n          attestations: false\n"
ATTESTATIONS_MISSING = "        with:\n          print-hash: true\n"
ATTESTATIONS_ONLY_COMMENTED = (
    "        with:\n"
    "          # attestations: true  <- a comment configures nothing\n"
    "          print-hash: true\n"
)


def _publish_workflow(permissions: str, publish_with: str) -> str:
    """A one-job publish workflow, parameterised on the two blocks under audit."""
    return (
        'name: Publish\non:\n  push:\n    tags: ["v*"]\n'
        "jobs:\n  publish:\n"
        f"{permissions}"
        "    steps:\n"
        f"      - uses: {PYPI_PUBLISH_ACTION}@ba38be9e461d3875417946c167d0b5f3d385a247\n"
        f"{publish_with}"
    )


def test_the_pypi_publish_step_carries_pep740_provenance() -> None:
    """This repo's real release path is signed, and the scan actually found it."""
    failures, publish_steps = _audit_provenance(WORKFLOWS)

    assert failures == []
    assert publish_steps > 0, "vacuous pass: no PyPI publish step was examined"


@pytest.mark.parametrize(
    ("permissions", "publish_with", "reason"),
    [
        pytest.param(OIDC_GRANTED, ATTESTATIONS_OFF, NO_ATTESTATIONS, id="attestations-false"),
        pytest.param(OIDC_GRANTED, ATTESTATIONS_MISSING, NO_ATTESTATIONS, id="attestations-absent"),
        pytest.param(
            OIDC_GRANTED,
            ATTESTATIONS_ONLY_COMMENTED,
            NO_ATTESTATIONS,
            id="attestations-only-in-a-comment",
        ),
        pytest.param(NO_PERMISSIONS, ATTESTED, NO_OIDC, id="no-permissions-block"),
        pytest.param(CONTENTS_READ_ONLY, ATTESTED, NO_OIDC, id="contents-read-only"),
    ],
)
def test_a_release_path_without_provenance_is_rejected(
    tmp_path: Path, permissions: str, publish_with: str, reason: str
) -> None:
    """Break the property, not the form: each fixture is a real way to lose provenance.

    `attestations-only-in-a-comment` is the load-bearing case. That file contains the
    literal text `attestations: true`, but only inside a comment, so a grep-based
    check waves it through. This audit parses YAML, so it does not.
    """
    workflow = tmp_path / "publish.yml"
    workflow.write_text(_publish_workflow(permissions, publish_with), encoding="utf-8")

    failures, publish_steps = _audit_provenance(tmp_path)

    assert failures == [f"publish.yml:publish: {reason}"]
    assert publish_steps == 1


def test_a_correctly_signed_release_path_is_accepted(tmp_path: Path) -> None:
    """Guard the opposite direction: a correct publish job must not be flagged."""
    workflow = tmp_path / "publish.yml"
    workflow.write_text(_publish_workflow(OIDC_GRANTED, ATTESTED), encoding="utf-8")

    assert _audit_provenance(tmp_path) == ([], 1)


def test_a_workflow_that_never_publishes_is_not_flagged(tmp_path: Path) -> None:
    """Only the release path is in scope — a test job with no OIDC scope is fine."""
    (tmp_path / "ci.yaml").write_text("jobs:\n  test:\n    steps:\n      - run: pytest\n")

    assert _audit_provenance(tmp_path) == ([], 0)
