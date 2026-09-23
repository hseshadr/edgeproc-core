"""The per-app error registry and its ``define_errors`` builder.

A ``Registry`` is the one place a site classifies raw failures into its codes,
describes them via its own i18n, serializes them to RFC 9457, and constructs
canonical exceptions. Mirrors ``@edgeproc/errors`` (TS) behaviour.
"""

from __future__ import annotations

import re
from typing import Final

from edgeproc_core.errors.canonical_error import CanonicalError, DuplicateCodeError
from edgeproc_core.errors.raw import http_status_of
from edgeproc_core.errors.types import (
    Catalog,
    CatalogEntry,
    Category,
    ErrorCode,
    MatchRule,
    Params,
    ProblemDetails,
    TFunction,
    _extension_members,
)

_INTERNAL_UNKNOWN: Final[str] = "internal.unknown"
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{(\w+)\}")


def _interpolate(template: str, params: Params) -> str:
    """Fill ``{name}`` placeholders from ``params``; leave unknown ones verbatim."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(params[name]) if name in params else match.group(0)

    return _PLACEHOLDER.sub(replace, template)


def _merge_catalogs(fragments: tuple[Catalog, ...]) -> dict[str, CatalogEntry]:
    """Merge fragments, rejecting a code that appears in more than one."""
    merged: dict[str, CatalogEntry] = {}
    for fragment in fragments:
        for code, entry in fragment.items():
            if code in merged:
                raise DuplicateCodeError(code)
            merged[code] = entry
    return merged


def _collect_matchers(catalog: Catalog) -> tuple[tuple[str, MatchRule], ...]:
    """The ``(code, match)`` pairs, in registration order — checked before status."""
    matchers = [(code, e.match) for code, e in catalog.items() if e.match is not None]
    return tuple(matchers)


def _build_status_index(catalog: Catalog) -> dict[int, str]:
    """Map HTTP status -> code; first code registered for a status wins."""
    index: dict[int, str] = {}
    for code, entry in catalog.items():
        for status in entry.http_status:
            index.setdefault(status, code)
    return index


def _first_status(entry: CatalogEntry | None) -> int | None:
    """The default Problem Details status: an entry's first registered status."""
    if entry is None or not entry.http_status:
        return None
    return entry.http_status[0]


def _problem_type_of(entry: CatalogEntry | None, code: ErrorCode) -> str:
    """The Problem Details ``type``: a registered URI, else the code itself."""
    if entry is not None and entry.problem_type is not None:
        return entry.problem_type
    return code


def _i18n_key_of(entry: CatalogEntry | None, code: ErrorCode) -> str:
    """The i18n key for a code: a registered override, else ``errors.<code>``."""
    if entry is not None and entry.i18n_key is not None:
        return entry.i18n_key
    return f"errors.{code}"


class Registry:
    """A per-app catalog with classify / describe / serialize / construct."""

    def __init__(self, catalog: dict[str, CatalogEntry]) -> None:
        self._catalog = catalog
        self._matchers = _collect_matchers(catalog)
        self._status_index = _build_status_index(catalog)

    @property
    def codes(self) -> tuple[str, ...]:
        """Every registered code, in registration order."""
        return tuple(self._catalog)

    def has(self, code: str) -> bool:
        """Whether a code is registered."""
        return code in self._catalog

    def get(self, code: str) -> CatalogEntry | None:
        """The entry for a code, or ``None``."""
        return self._catalog.get(code)

    def classify(self, raw: object) -> ErrorCode:
        """Turn a raw transport/LLM failure into a code (fallback ``internal.unknown``)."""
        for code, match in self._matchers:
            if match(raw):
                return code
        return self._classify_by_status(raw)

    def _classify_by_status(self, raw: object) -> ErrorCode:
        status = http_status_of(raw)
        if status is None:
            return _INTERNAL_UNKNOWN
        return self._status_index.get(status, _INTERNAL_UNKNOWN)

    def describe(
        self, code: ErrorCode, params: Params | None = None, t: TFunction | None = None
    ) -> str:
        """Resolve the human text for a code via i18n, falling back to English."""
        values: Params = params if params is not None else {}
        entry = self._catalog.get(code)
        localized = self._translate(code, entry, values, t)
        if localized is not None:
            return localized
        return self._default_text(code, entry, values)

    def _translate(
        self, code: ErrorCode, entry: CatalogEntry | None, values: Params, t: TFunction | None
    ) -> str | None:
        if t is None:
            return None
        key = _i18n_key_of(entry, code)
        localized = t(key, values)
        return localized if localized != key else None

    def _default_text(self, code: ErrorCode, entry: CatalogEntry | None, values: Params) -> str:
        template = entry.en if entry is not None else None
        if template is None:
            return code
        return _interpolate(template, values)

    def to_problem_details(
        self,
        code: ErrorCode,
        params: Params | None = None,
        *,
        status: int | None = None,
        title: str | None = None,
        instance: str | None = None,
    ) -> ProblemDetails:
        """Serialize a code to the RFC 9457 Problem Details shape.

        Params become public extension members, except that reserved names
        (``type``, ``title``, ``status``, ``detail``, ``instance``, ``__proto__``,
        ``constructor``, ``prototype``, ``toJSON``), non-``str`` or ``str``-subclass
        keys, and values that are not a ``str``, ``int``, or finite ``float``
        (``bool`` included) are dropped. Every param still reaches
        :meth:`describe` for title interpolation."""
        values: Params = params if params is not None else {}
        entry = self._catalog.get(code)
        return ProblemDetails(
            type=_problem_type_of(entry, code),
            title=title if title is not None else self.describe(code, values),
            status=status if status is not None else _first_status(entry),
            instance=instance,
            members=_extension_members(values),
        )

    def create(self, code: ErrorCode, params: Params | None = None) -> CanonicalError:
        """Construct a :class:`CanonicalError`, looking category up from the catalog."""
        entry = self._catalog.get(code)
        category = entry.category if entry is not None else Category.INTERNAL
        return CanonicalError(code, category, params)


def define_errors(*fragments: Catalog) -> Registry:
    """Build a per-app registry from one or more catalog fragments.

    Passing fragments as separate arguments gives runtime duplicate-code
    detection across them: ``define_errors(starter_pack, own_codes)``.
    """
    return Registry(_merge_catalogs(fragments))
