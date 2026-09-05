"""Invariants of the secret settings (ADR 0067 follow-ups, ADR 0069).

`tests/test_config.py` writes "the secret is not in the output" by
hand, four times — once per `SecretStr` field, against a constant
somebody chose. That proves the mask *runs*. It does not prove the
mask *holds*, for the reason `test_property_redaction.py` gives about
the six credentials it generalises: the value that leaks is by
definition the one nobody wrote down.

So the masking property here is derived, not restated. It reads the
`SecretStr` fields off `Settings.model_fields`, which means a secret
added tomorrow is covered the day it lands rather than the day
somebody remembers to copy a test class. Today that is four fields:
`log_principal_salt` (WO-C3), `anthropic_api_key` (WO-C4), and the
two WO-D3 converted — `api_keys` and `semantic_scholar_api_key`.

The other half is the half a masking property cannot see, and it is
why WO-D3 was not two retypes. Both of these fields have a *consumer*
that needs the raw bytes:

- `api_keys` is the inbound keystore. `src/api/auth.py::parse_api_keys`
  splits it into the map `_lookup_principal` authenticates every
  request against. A conversion that masked the field and unwrapped
  it in the wrong place would build a keystore keyed on `**********`:
  masked perfectly, authenticating nobody — or, worse, authenticating
  whoever sends the mask.
- `semantic_scholar_api_key` is an outbound credential that
  `src/tools/semantic_scholar.py::_headers` puts on the wire. The
  same wrong unwrap sends `**********` as `x-api-key`, Semantic
  Scholar answers 403, and `_get_json` swallows a non-2xx into a
  warning — so the symptom is silently empty enrichment.

Each therefore gets a paired property: *the secret is destroyed in
every output path, and the raw value still reaches the one consumer
that needs it*. Split into two tests rather than one, so a failure
names which half broke.

Generators stay ASCII on purpose. `_lookup_principal` encodes the
presented value back to latin-1 (Starlette decodes headers that way)
and the configured secret to utf-8; those agree for ASCII and
deliberately do not above 0x7f, which is `src/api/auth.py`'s
documented behaviour and a property about the header codec rather
than about this retype.

Minimum secret length is 12 for the same kind of reason. A
one-character secret is a substring of almost any `repr`, so "the
secret is absent from the output" would be false for a reason no
masking scheme could fix — the property would be asserting something
nobody claimed. Twelve is past every incidental token in a `Settings`
repr, and the `assume` below covers the rest.
"""

from __future__ import annotations

import string
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Final

import pytest
from hypothesis import HealthCheck, assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from pydantic import SecretStr

from src.api.auth import _lookup_principal, parse_api_keys
from src.config import Settings
from src.tools import semantic_scholar as s2_module

pytestmark = [pytest.mark.unit, pytest.mark.property, pytest.mark.security]

#: What `SecretStr` renders as in every masked output path. Pinned as
#: a constant so the "the mask authenticates nobody" properties below
#: compare against the same string pydantic actually emits.
MASK: Final = "**********"

#: Per-field example budget for the sweeps that are parametrized over
#: every secret field. Same reasoning as `test_property_config.py`:
#: the profile's full budget times the field count would spend a large
#: share of the tier's 60-second target in one file, and a `Settings`
#: construction plus six renderings is not a cheap example.
FIELD_EXAMPLES: Final = 25

#: Characters a secret may contain for the *masking* properties. Wide
#: on purpose, including the `,` and `:` that give `api_keys` its
#: structure: masking is a property of the type, and must not depend
#: on the value having — or not having — a parseable shape.
_SECRET_CHARS: Final = string.ascii_letters + string.digits + "-_.:/,+= @"

#: Characters for the round-trip properties, where the value has to
#: survive `parse_api_keys`' per-entry `strip()` and the `,` split
#: unchanged. `:` stays in the *secret* alphabet deliberately — the
#: parser splits on the first colon only, and a secret containing one
#: is the case that proves it.
_NAME_CHARS: Final = string.ascii_letters + string.digits + "-_"
_KEY_CHARS: Final = string.ascii_letters + string.digits + "-_.:/+="


def secret_fields() -> list[str]:
    """Every `SecretStr` field on `Settings`, read off the model.

    Derived rather than listed so the sweep covers a secret added
    after this file was written. A hand-maintained list would be a
    second source of truth, and the second source is the one that
    goes stale — the same argument `test_property_config.py` makes
    about numeric bounds.
    """
    return sorted(
        name
        for name, field in Settings.model_fields.items()
        if field.annotation is SecretStr
    )


SECRET_FIELDS: Final = secret_fields()


@lru_cache(maxsize=1)
def _baseline_renderings() -> str:
    """Every output path of a `Settings` built with no secret set.

    Used only by `assume`. A generated secret that happens to be a
    substring of ordinary `Settings` text — a field name, a default,
    a URL — would falsify "the secret is absent from the output" for
    a reason that has nothing to do with masking, and a property that
    ignored that would be reporting a leak it had invented.
    """
    blank = Settings(**{name: "" for name in SECRET_FIELDS})
    return "".join(
        [
            repr(blank),
            str(blank),
            str(blank.model_dump()),
            str(blank.model_dump(mode="json")),
            blank.model_dump_json(),
        ]
    )


def output_paths(built: Settings, name: str) -> dict[str, str]:
    """Every way a `Settings` or one of its secret fields becomes text.

    The six ADR 0067 names, plus the two field-level ones — an
    f-string of the wrapper is the mistake `src/config.py` warns
    about by name, and it is the one that would authenticate as
    `**********` rather than fail loudly.
    """
    field = getattr(built, name)
    return {
        "repr(settings)": repr(built),
        "str(settings)": str(built),
        "f-string of settings": f"{built}",
        "model_dump()": str(built.model_dump()),
        'model_dump(mode="json")': str(built.model_dump(mode="json")),
        "model_dump_json()": built.model_dump_json(),
        "repr(field)": repr(field),
        "f-string of field": f"{field}",
    }


@st.composite
def secret_value(draw: st.DrawFn) -> str:
    """A secret with no assumed shape, long enough to be distinctive."""
    value = draw(st.text(alphabet=_SECRET_CHARS, min_size=12, max_size=64))
    # A whitespace-only value is *unset* by design (the blank-is-unset
    # before-validators), so there would be no secret left to leak and
    # the property would pass vacuously.
    assume(value.strip())
    assume(value not in _baseline_renderings())
    return value


@st.composite
def keystore_pairs(draw: st.DrawFn) -> list[tuple[str, str]]:
    """`[(name, secret), ...]` for a keystore `parse_api_keys` accepts.

    Names and secrets are both unique: `parse_api_keys` rejects a
    duplicate of either (ADR 0042 — two secrets sharing a name would
    silently merge two tenants' rows), so a generator that produced
    them would be testing the duplicate check, not the round trip.
    """
    return draw(
        st.lists(
            st.tuples(
                st.text(alphabet=_NAME_CHARS, min_size=1, max_size=12),
                st.text(alphabet=_KEY_CHARS, min_size=12, max_size=40),
            ),
            min_size=1,
            max_size=4,
            unique_by=(lambda pair: pair[0], lambda pair: pair[1]),
        )
    )


def render_keystore(pairs: list[tuple[str, str]]) -> str:
    """The `API_KEYS` string an operator would export for `pairs`."""
    return ",".join(f"{name}:{secret}" for name, secret in pairs)


@contextmanager
def s2_settings(**overrides: object) -> Iterator[None]:
    """Swap `semantic_scholar`'s module-level `settings` for one example.

    A context manager rather than `monkeypatch`, because Hypothesis
    refuses a function-scoped fixture inside `@given`: the fixture is
    set up once and every example after the first would run against
    whatever the previous one left behind.
    """
    original = s2_module.settings
    s2_module.settings = Settings(**overrides)
    try:
        yield
    finally:
        s2_module.settings = original


# ---------------------------------------------------------------------------
# The mask holds, for every secret field and any value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SECRET_FIELDS)
@hyp_settings(
    max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow]
)
@given(secret=secret_value())
def test_a_secret_field_is_destroyed_in_every_output_path(
    name: str, secret: str
) -> None:
    """No generated secret appears in any way a `Settings` becomes text.

    The failure this pins is not hypothetical for three of the four
    fields: `Settings` is constructed in some thirty test modules and
    pydantic's `__repr__` prints every field, so before WO-C3, WO-C4
    and WO-D3 a `-vv` assertion diff, a `print(settings)` in a
    debugger or any deliberate settings dump carried the live value.
    """
    built = Settings(**{name: secret})
    for path, rendered in output_paths(built, name).items():
        assert secret not in rendered, f"{name} leaked through {path}"


@pytest.mark.parametrize("name", SECRET_FIELDS)
@hyp_settings(
    max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow]
)
@given(secret=secret_value())
def test_a_secret_field_round_trips_through_the_wrapper_unchanged(
    name: str, secret: str
) -> None:
    """The converse. A field that returned `""` would mask perfectly.

    Masking is only half a promise: the value has to survive intact,
    byte for byte, or the credential that reaches the consumer is not
    the one the operator exported. Only a *blank* is special, and
    `secret_value` excludes blanks, so nothing here may be stripped.
    """
    built = Settings(**{name: secret})
    assert getattr(built, name).get_secret_value() == secret
    assert built.model_dump()[name].get_secret_value() == secret


@pytest.mark.parametrize("name", SECRET_FIELDS)
@given(blank=st.text(alphabet=" \t\n\r", max_size=8))
def test_a_blank_secret_is_unset_for_every_secret_field(
    name: str, blank: str
) -> None:
    """Whitespace is "not configured", not a credential made of spaces.

    All four fields carry the same before-validator, and each one is
    load-bearing somewhere different: a blank `ANTHROPIC_API_KEY`
    would earn a 401 instead of "not set in .env", a blank
    `LOG_PRINCIPAL_SALT` would salt the fleet with `""`, a blank
    `SEMANTIC_SCHOLAR_API_KEY` would send `x-api-key: " "` and fail
    enrichment closed. Asserted here once, over every whitespace
    string rather than the three the unit tests parametrize.
    """
    built = Settings(**{name: blank})
    assert getattr(built, name).get_secret_value() == ""
    assert bool(getattr(built, name)) is False


# ---------------------------------------------------------------------------
# `api_keys` — the raw value still reaches the inbound authenticator
# ---------------------------------------------------------------------------


@given(pairs=keystore_pairs())
def test_the_keystore_is_destroyed_in_every_output_path(
    pairs: list[tuple[str, str]],
) -> None:
    """Every secret in the keystore, not just the string as a whole.

    `api_keys` is the one field here that holds more than one
    credential, so an implementation that masked the *string* while
    leaving a parsed copy on the model would pass a whole-value check
    and still print each secret. Assert per secret.
    """
    raw = render_keystore(pairs)
    assume(raw not in _baseline_renderings())
    built = Settings(api_keys=raw)
    rendered = output_paths(built, "api_keys")
    for _name, secret in pairs:
        assume(secret not in _baseline_renderings())
        for path, text in rendered.items():
            assert secret not in text, f"keystore secret leaked through {path}"


@given(pairs=keystore_pairs())
def test_every_configured_secret_still_authenticates(
    pairs: list[tuple[str, str]],
) -> None:
    """The consumer half: the request path still admits the real key.

    Asserted through `_lookup_principal` — the `hmac.compare_digest`
    loop `require_principal` actually calls — rather than through the
    parsed dict, because the dict is an implementation detail and the
    comparator is the guard. Each secret must map to *its own*
    principal name: a keystore that authenticated every caller as the
    first principal would satisfy a weaker check and silently merge
    two tenants' rows under ADR 0036.
    """
    keystore = parse_api_keys(Settings(api_keys=render_keystore(pairs)).api_keys)

    assert len(keystore) == len(pairs)
    for name, secret in pairs:
        principal = _lookup_principal(secret, keystore)
        assert principal is not None, "a configured secret was refused"
        assert principal.key_id == name


@given(pairs=keystore_pairs())
def test_the_mask_authenticates_nobody(pairs: list[tuple[str, str]]) -> None:
    """The trap WO-C4 found next door, asserted on the inbound path.

    Two shapes of the same mistake. Presenting `**********` as a key
    must not authenticate — otherwise the mask that protects the
    keystore in a log becomes a credential anyone reading that log
    can replay. And building the keystore out of the *stringified*
    wrapper — `parse_api_keys(SecretStr(str(settings.api_keys)))`,
    the unwrap-in-the-wrong-place — must fail loudly rather than
    yield a keystore that quietly matches nothing.
    """
    for _name, secret in pairs:
        assume(secret != MASK)

    built = Settings(api_keys=render_keystore(pairs))
    keystore = parse_api_keys(built.api_keys)
    assert _lookup_principal(MASK, keystore) is None

    with pytest.raises(ValueError, match="separator"):
        parse_api_keys(SecretStr(str(built.api_keys)))


@given(
    secret=st.text(alphabet=_KEY_CHARS.replace(":", ""), min_size=12, max_size=40)
)
def test_a_separatorless_entry_is_refused_without_quoting_it(
    secret: str,
) -> None:
    """An entry with no `:` is a bare secret, and the error said so aloud.

    `parse_api_keys` used to raise `f"api_keys entry {entry!r} …"`
    from inside `create_app`, which put the value into a startup log,
    a container's stderr and any CI transcript that captured it —
    an output path no amount of masking on the *field* would have
    closed. WO-D3 replaced the quoted entry with its position.
    """
    with pytest.raises(ValueError) as raised:
        parse_api_keys(SecretStr(secret))
    assert secret not in str(raised.value)


@given(secret=st.text(alphabet=_KEY_CHARS, min_size=12, max_size=40))
def test_an_entry_with_no_principal_name_is_refused_without_quoting_it(
    secret: str,
) -> None:
    """The second malformed shape, `:secret`, and the same rule.

    A missing name is the likelier typo of the two — a stray leading
    colon, or a `${VAR}` that interpolated empty — and everything
    after it is the secret.
    """
    with pytest.raises(ValueError) as raised:
        parse_api_keys(SecretStr(f":{secret}"))
    assert secret not in str(raised.value)


# ---------------------------------------------------------------------------
# `semantic_scholar_api_key` — the raw value still reaches the wire
# ---------------------------------------------------------------------------


@given(key=secret_value())
def test_the_semantic_scholar_key_reaches_the_header_raw(key: str) -> None:
    """The consumer half for the outbound credential.

    `_headers` is the only reader, and the header dict is the only
    place the raw value is allowed to appear. Asserted as an equality
    on the whole dict rather than a containment check, so a build
    that also stashed the key under a second header key would fail.
    """
    with s2_settings(semantic_scholar_api_key=key):
        assert s2_module._headers() == {"x-api-key": key}


@given(key=secret_value())
def test_the_semantic_scholar_key_never_reaches_the_header_masked(
    key: str,
) -> None:
    """The mutation this file exists to make loud.

    `{"x-api-key": f"{settings.semantic_scholar_api_key}"}` is one
    plausible edit away from the real code and sends `**********` to
    Semantic Scholar, which 403s, which `_get_json` swallows into a
    warning — so enrichment goes quietly empty and nothing in the
    logs says why.
    """
    with s2_settings(semantic_scholar_api_key=key):
        assert s2_module._headers()["x-api-key"] != MASK


@given(blank=st.text(alphabet=" \t\n\r", max_size=8))
def test_a_blank_semantic_scholar_key_sends_no_header_at_all(
    blank: str,
) -> None:
    """Unset means anonymous, and whitespace has to mean unset.

    Without the before-validator this sends `x-api-key: " "` — a
    *bad* key rather than no key — and S2's answer to a bad key is
    403, not the anonymous rate limit the fallback is designed to
    reach.
    """
    with s2_settings(semantic_scholar_api_key=blank):
        assert s2_module._headers() == {}
