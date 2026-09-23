"""The public type surface for ``edgeproc_core.errors``.

A canonical error is ``{code, params, category}`` and serializes to the RFC 9457
Problem Details shape on the wire. The :class:`CatalogEntry` for a code is the
typed contract for that error's params. Mirrors ``@edgeproc/errors`` (TS).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

#: A stable, namespaced error identity, e.g. ``ai.provider.out_of_credits``.
type ErrorCode = str

#: A value that may be interpolated into an error description.
type ParamValue = str | int | float

#: A read-only bag of interpolation values, keyed by param name.
type Params = Mapping[str, ParamValue]

#: A predicate that inspects a raw failure and claims it for a code.
type MatchRule = Callable[[object], bool]

#: A consumer-provided i18next/Babel-style translator: ``t("errors.<code>", params)``.
#: By contract it returns the key verbatim when the resource is missing, which is
#: our signal to fall back to the catalog default English.
type TFunction = Callable[[str, Params], str]


class Category(StrEnum):
    """How a failure is treated by UI + telemetry (retry vs. "open Settings" …)."""

    PROVIDER = "provider"
    CONFIG = "config"
    NETWORK = "network"
    TIMEOUT = "timeout"
    DEVICE = "device"
    INTEGRITY = "integrity"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One code's typed contract: its category, allowed params, and match rule."""

    category: Category
    params: tuple[str, ...] = ()
    i18n_key: str | None = None
    http_status: tuple[int, ...] = ()
    problem_type: str | None = None
    en: str | None = None
    match: MatchRule | None = None


#: A map of code -> entry. Each site declares and owns its own.
type Catalog = Mapping[str, CatalogEntry]


#: Member names params never supply. ``type`` and ``title`` come from the catalog,
#: ``status`` and ``instance`` from keyword options, and ``detail`` is set only
#: explicitly (RFC 9457). ``__proto__``, ``constructor``, ``prototype``, and ``toJSON``
#: are special to JavaScript consumers of the wire object: they re-parent objects,
#: feed prototype-pollution gadgets, or hijack ``JSON.stringify``. Mirrors the TS
#: package.
_RESERVED_PROBLEM_MEMBERS: frozenset[str] = frozenset(
    {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "__proto__",
        "constructor",
        "prototype",
        "toJSON",
    }
)


def _is_extension_key(key: object) -> bool:
    """An exact ``str`` that names no reserved member.

    The exact-type check runs first: a ``str`` subclass can override ``__hash__``
    and ``__eq__`` to slip past the reserved-name membership test while still
    spelling ``status`` or ``type`` on the wire."""
    return type(key) is str and key not in _RESERVED_PROBLEM_MEMBERS


def _plain_number(value: int | float) -> ParamValue | None:
    """``value`` as an exact ``int`` or finite ``float``; ``None`` if non-finite."""
    if isinstance(value, int):
        return int.__int__(value)
    plain = float.__float__(value)
    return plain if math.isfinite(plain) else None


def _wire_value(value: object) -> ParamValue | None:
    """``value`` as a plain ``str``, ``int``, or finite ``float``; ``None`` to drop it.

    ``bool`` is an ``int`` subclass but not a number on the wire, so it is dropped.
    Subclasses of the allowed types are narrowed to the exact builtin."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, int | float):
        return _plain_number(value)
    return None


def _extension_members(params: Mapping[str, object]) -> dict[str, ParamValue]:
    """Copy the wire-safe params: exact-``str`` non-reserved keys, scalar values."""
    members: dict[str, ParamValue] = {}
    for key, value in params.items():
        plain = _wire_value(value)
        if plain is not None and _is_extension_key(key):
            members[key] = plain
    return members


@dataclass(frozen=True, slots=True)
class ProblemDetails:
    """RFC 9457 Problem Details. Params ride along as extension ``members``.

    Members are public: they go on the wire, so never pass secrets as params.
    Only members with an exact-``str`` key and a ``str``, ``int``, or finite
    ``float`` value reach the wire form (``bool`` is dropped). A member named
    ``type``, ``title``, ``status``, ``detail``, ``instance``, ``__proto__``,
    ``constructor``, ``prototype``, or ``toJSON`` is reserved and never does."""

    type: str
    title: str
    status: int | None = None
    instance: str | None = None
    detail: str | None = None
    members: Mapping[str, ParamValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, ParamValue]:
        """Flatten to the RFC 9457 wire object: wire-safe members, then core fields."""
        wire: dict[str, ParamValue] = _extension_members(self.members)
        wire["type"] = self.type
        wire["title"] = self.title
        if self.status is not None:
            wire["status"] = self.status
        if self.instance is not None:
            wire["instance"] = self.instance
        if self.detail is not None:
            wire["detail"] = self.detail
        return wire
