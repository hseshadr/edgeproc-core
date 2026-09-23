"""``to_problem_details()`` — RFC 9457 Problem Details conformance."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from edgeproc_core.errors import (
    CatalogEntry,
    Category,
    ProblemDetails,
    define_errors,
    starter_pack,
)

registry = define_errors(starter_pack)


def test_should_use_the_code_as_type_when_no_problem_type_registered() -> None:
    # Given a code with no problemType URI
    # When serialized
    # Then the code itself is the Problem Details type
    pd = registry.to_problem_details("ai.provider.out_of_credits")
    assert pd.type == "ai.provider.out_of_credits"


def test_should_prefer_a_registered_problem_type_uri_as_type() -> None:
    # Given a code with an explicit problemType URI
    reg = define_errors(
        {
            "app.teapot": CatalogEntry(
                category=Category.INTERNAL,
                problem_type="https://example.com/probs/teapot",
                en="I'm a teapot.",
            )
        }
    )
    # When serialized
    # Then the URI is used as the type
    assert reg.to_problem_details("app.teapot").type == "https://example.com/probs/teapot"


def test_should_derive_title_from_describe_when_none_supplied() -> None:
    # Given no explicit title
    # When serialized
    # Then the title is the default-English description
    pd = registry.to_problem_details("net.unreachable")
    assert pd.title == "Couldn't reach the server. Check your connection and try again."


def test_should_use_an_explicit_title_when_supplied() -> None:
    # Given an explicit title override
    # When serialized
    # Then the override wins
    pd = registry.to_problem_details("ai.provider.rate_limited", title="Slow down")
    assert pd.title == "Slow down"


def test_should_default_status_to_the_first_registered_http_status() -> None:
    # Given a code whose first registered status is 402
    # When serialized
    # Then status defaults to 402
    assert registry.to_problem_details("ai.provider.out_of_credits").status == 402


def test_should_prefer_an_explicit_status_and_carry_instance() -> None:
    # Given an explicit status + instance
    pd = registry.to_problem_details("ai.provider.server_error", status=503, instance="/v1/chat/42")
    # When serialized
    # Then both are carried through
    assert pd.status == 503
    assert pd.instance == "/v1/chat/42"


def test_should_omit_status_when_neither_option_nor_http_status() -> None:
    # Given a code with no registered status and no override
    # When serialized
    # Then status stays None and is dropped from the wire form
    pd = registry.to_problem_details("internal.unknown")
    assert pd.status is None
    assert "status" not in pd.to_dict()


def test_should_spread_params_as_extension_members() -> None:
    # Given params on a code
    pd = registry.to_problem_details(
        "ai.provider.out_of_credits", {"creditsLeft": 0, "currency": "USD"}
    )
    # When serialized to the wire form
    wire = pd.to_dict()
    # Then params sit alongside the core RFC 9457 fields
    assert pd.members == {"creditsLeft": 0, "currency": "USD"}
    assert wire["type"] == "ai.provider.out_of_credits"
    assert wire["status"] == 402
    assert wire["creditsLeft"] == 0
    assert wire["currency"] == "USD"
    assert isinstance(wire["title"], str)


def test_should_not_let_a_member_override_a_core_field_in_the_wire_form() -> None:
    # Given a stray param that collides with a core field name
    pd = registry.to_problem_details("internal.unknown", {"type": "spoofed"})
    # When serialized
    # Then the canonical type wins over the member
    assert pd.to_dict()["type"] == "internal.unknown"


def test_should_carry_every_field_including_instance_and_detail_into_the_wire_form() -> None:
    # Given a Problem Details carrying instance, detail and extension members
    pd = ProblemDetails(
        type="app.x",
        title="X",
        status=500,
        instance="/req/1",
        detail="boom",
        members={"n": 1},
    )
    # When flattened to the wire form
    # Then every RFC 9457 field is present alongside the members
    assert pd.to_dict() == {
        "n": 1,
        "type": "app.x",
        "title": "X",
        "status": 500,
        "instance": "/req/1",
        "detail": "boom",
    }


_RESERVED_PARAMS: dict[str, str | int] = {
    "type": "https://attacker.example/forged",
    "title": "Forged title",
    "status": 200,
    "detail": "Forged detail",
    "instance": "/forged",
}


def test_should_never_let_params_supply_reserved_rfc9457_members() -> None:
    # Given params that name every reserved RFC 9457 member plus one extension
    pd = registry.to_problem_details("ai.provider.out_of_credits", {**_RESERVED_PARAMS, "n": 0})
    # When serialized
    # Then reserved names are dropped from members and the wire keeps registry values
    assert pd.members == {"n": 0}
    assert pd.to_dict() == {
        "n": 0,
        "type": "ai.provider.out_of_credits",
        "title": registry.describe("ai.provider.out_of_credits"),
        "status": 402,
    }


def test_should_not_let_a_param_fill_a_reserved_member_the_registry_leaves_unset() -> None:
    # Given a code with no registered status and reserved-named params
    pd = registry.to_problem_details("internal.unknown", _RESERVED_PARAMS)
    # When serialized
    # Then status, detail, and instance stay absent rather than coming from params
    assert pd.to_dict() == {
        "type": "internal.unknown",
        "title": registry.describe("internal.unknown"),
    }


def test_should_keep_a_reserved_named_param_available_to_the_title_template() -> None:
    # Given a template that interpolates a param named like a reserved member
    reg = define_errors(
        {"app.detail": CatalogEntry(category=Category.INTERNAL, en="Failed: {detail}")}
    )
    # When serialized
    pd = reg.to_problem_details("app.detail", {"detail": "disk full"})
    # Then the title uses it, but it never becomes the detail member
    assert pd.to_dict() == {"type": "app.detail", "title": "Failed: disk full"}


def test_should_drop_reserved_names_from_directly_constructed_members() -> None:
    # Given a hand-built Problem Details whose members name reserved fields
    pd = ProblemDetails(type="app.x", title="X", members={**_RESERVED_PARAMS, "n": 1})
    # When flattened
    # Then reserved names never leak from members into the wire form
    assert pd.to_dict() == {"n": 1, "type": "app.x", "title": "X"}


#: Keys a JavaScript consumer treats as special. ``__proto__`` re-parents an object
#: built by assignment or ``Object.assign``, ``constructor``/``prototype`` feed
#: prototype-pollution gadgets, and ``toJSON`` hijacks ``JSON.stringify``. Mirrors
#: the key denylist of ``@edgeproc/errors``.
_PROTOTYPE_KEYS = ("__proto__", "constructor", "prototype", "toJSON")


def test_should_drop_a_proto_param_parsed_from_untrusted_json() -> None:
    # Given the reproduced payload: untrusted JSON carrying a __proto__ member
    params = json.loads('{"__proto__":{"isAdmin":true}}')
    # When serialized to the wire form
    wire = registry.to_problem_details("internal.unknown", params).to_dict()
    # Then __proto__ never reaches the wire
    assert "__proto__" not in wire
    assert "__proto__" not in json.dumps(wire)


@pytest.mark.parametrize("key", _PROTOTYPE_KEYS)
def test_should_never_emit_a_prototype_sensitive_key_even_with_a_scalar_value(key: str) -> None:
    # Given a prototype-sensitive param name carrying an otherwise valid value
    pd = registry.to_problem_details("internal.unknown", {key: "x", "n": 1})
    # When serialized
    # Then only the ordinary param survives, in members and on the wire
    assert pd.members == {"n": 1}
    assert key not in pd.to_dict()


@pytest.mark.parametrize(
    "value",
    [
        {"isAdmin": True},
        ["a", "b"],
        None,
        True,
        False,
        b"bytes",
        math.nan,
        math.inf,
        -math.inf,
        object(),
    ],
    ids=["dict", "list", "none", "true", "false", "bytes", "nan", "inf", "-inf", "object"],
)
def test_should_drop_a_param_whose_value_is_not_a_string_or_finite_number(value: object) -> None:
    # Given a param whose value is not a string or a finite number
    params: dict[str, Any] = {"bad": value, "n": 1}
    # When serialized
    pd = registry.to_problem_details("internal.unknown", params)
    # Then it is dropped, and the wire stays strict-JSON serializable
    assert pd.members == {"n": 1}
    assert "bad" not in json.dumps(pd.to_dict(), allow_nan=False)


def test_should_keep_strings_ints_and_finite_floats_as_extension_members() -> None:
    # Given one param of each wire-safe scalar type
    pd = registry.to_problem_details("internal.unknown", {"s": "USD", "i": 0, "f": 1.5})
    # When serialized
    # Then all three ride along unchanged
    assert pd.members == {"s": "USD", "i": 0, "f": 1.5}


class _EvasiveKey(str):
    """A key that spells a reserved name but defeats hash/equality membership tests."""

    __slots__ = ()

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other


def test_should_drop_a_str_subclass_key_that_evades_the_reserved_name_check() -> None:
    # Given the reproduced bypass: str-subclass keys spelling reserved members
    params: dict[Any, Any] = {_EvasiveKey("status"): 200, _EvasiveKey("type"): "forged", "n": 1}
    # When an unregistered code is serialized
    wire = registry.to_problem_details("internal.unknown", params).to_dict()
    encoded = json.dumps(wire)
    # Then neither a forged status nor a duplicate type reaches the wire
    assert '"status"' not in encoded
    assert encoded.count('"type"') == 1
    assert wire == {
        "n": 1,
        "type": "internal.unknown",
        "title": registry.describe("internal.unknown"),
    }


class _TaggedStr(str):
    __slots__ = ()


class _Real(float):
    __slots__ = ()


def test_should_emit_subclassed_scalar_values_as_their_plain_builtin_type() -> None:
    # Given scalar values that are subclasses of str, int, and float
    params: dict[str, Any] = {"s": _TaggedStr("USD"), "e": Category.NETWORK, "f": _Real(2.5)}
    # When serialized
    members = registry.to_problem_details("internal.unknown", params).members
    # Then the wire carries exact builtins with the same value
    assert members == {"s": "USD", "e": "network", "f": 2.5}
    assert [type(value) for value in members.values()] == [str, str, float]


def test_should_filter_directly_constructed_members_the_same_way() -> None:
    # Given a hand-built Problem Details carrying unsafe keys and values
    members: dict[Any, Any] = {"__proto__": "x", "obj": {"a": 1}, "nan": math.nan, "n": 1}
    pd = ProblemDetails(type="app.x", title="X", members=members)
    # When flattened
    # Then only the safe member reaches the wire
    assert pd.to_dict() == {"n": 1, "type": "app.x", "title": "X"}
