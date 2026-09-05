"""Invariants of log redaction (ADR 0042, ADR 0067, ADR 0069, ADR 0084).

`tests/test_log_redaction.py:25` already writes the property this file
generalises — "the secret is never in the output" — by hand, for a
handful of credentials someone chose. A handful is enough to prove a
rule runs; it is not enough to prove a rule *holds*, because the
credential that leaks is by definition the one nobody wrote down.

**The properties here are parametrised over the rule set itself, not
over a list of cases.** `redact_text` is `REDACTION_RULES` applied in
order, so this file imports that tuple and derives its test ids from
it. `test_every_rule_has_a_secret_generator` then closes the loop in
both directions: a rule added without a generator fails, and a
generator left behind by a deleted rule fails too. That is the
difference between "the five rules I remembered are tested" — which is
how ADR 0067 shipped a rule set with no gateway-credential rule in it,
and how WO-C4 came to measure `gw_live_…` passing through untouched —
and "every rule that exists is tested".

Three properties run over every rule:

- **`test_every_rule_destroys_its_secret`** — the generated secret is
  not in the output. The one-sentence invariant, for all of them.
- **`test_every_rule_is_load_bearing`** — with *that rule alone*
  removed from `REDACTION_RULES`, the same secret comes back. This is
  the mutation test written down: it fails if a rule is deleted, and
  it also fails if a rule is added that nothing but another rule was
  already catching.
- **`test_a_prefixed_rule_keeps_the_issuer_prefix`** — what survives
  is as load-bearing as what does not. `ghp_***` names the credential
  to revoke; `***[40 chars]` leaves an operator guessing.

The other half matters as much. A function that returned `"***"`
unconditionally would satisfy every property above, so
`test_legitimate_content_survives_byte_for_byte` generates the content
this system actually logs — arXiv ids, DOIs, model names, trace and
span ids, digests, snake_case identifiers carrying `live` and `test` as
words — and asserts it comes back unchanged. A rule that eats a paper
id is worse than the gap it closes, because it damages every line
rather than one. Idempotence pins the boundary between the two halves,
since a rule that kept finding new secrets in its own output would be
rewriting text it had already cleared.

Every generated secret is placed whitespace-delimited in its
surrounding text. That is not a convenience: most of the rules are
anchored on a word boundary or a character-class lookbehind, so
`xsk-AKIA...` is deliberately not a match, and a property that ignored
the anchor would be asserting something the rules never claimed.
"""

from __future__ import annotations

import asyncio
import logging
import string
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any, Final, NamedTuple

import pytest
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

import src.observability.logging as logging_module
from src.api.admin_migrate import assign_conversation_owner, assign_job_owner
from src.observability import hash_principal, redact_text, redact_url

# The prefix registries are read from the module rather than retyped
# here, so a prefix added to either list is exercised by the generator
# on the next run without anybody remembering to copy it across.
from src.observability.logging import (
    _DASHED_VENDOR_TOKEN_PREFIXES,
    _VENDOR_TOKEN_PREFIXES,
    REDACTION_RULES,
)

pytestmark = [pytest.mark.unit, pytest.mark.property, pytest.mark.security]

#: Words for the text a secret is embedded in. Lowercase letters only,
#: so the context can never itself be mistaken for a credential and
#: make a passing assertion mean nothing.
_CONTEXT = st.lists(
    st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8),
    max_size=8,
).map(" ".join)

_TOKEN_CHARS = string.ascii_letters + string.digits + "_-"
_BEARER_CHARS = string.ascii_letters + string.digits + "-."
_BASE64_CHARS = string.ascii_letters + string.digits + "+/"
_BASE64URL_CHARS = string.ascii_letters + string.digits + "-_"
_ALNUM = string.ascii_letters + string.digits
_HEX = "0123456789abcdef"

#: The alphabet for the idempotence property: every character any of
#: the rules keys on, so the generator can build the collisions between
#: them that a hand-written example never would.
_ADVERSARIAL = string.ascii_letters + string.digits + " @:/-._+=~%\n"

#: The rule names, in order. Test ids are these names, so a failure
#: report says which rule stopped holding.
RULE_NAMES: Final[tuple[str, ...]] = tuple(rule.name for rule in REDACTION_RULES)


class Credential(NamedTuple):
    """What a secret generator produces.

    Three fields and not one, because for half the rules they differ.
    `emitted` is the string that goes into the log line — a whole
    connection URL, a whole `Authorization` value. `secret` is the part
    that must not come back out, which for the prefixed rules is the
    body alone: `gw_live_` survives on purpose, and asserting that the
    whole token is gone would quietly pass on a rule that redacted
    nothing but the prefix. `prefix` is what the rule promises to keep,
    carried rather than derived — recovering it from the emitted string
    by searching for the secret puts `AKIAAAAA…` one repeated character
    away from a wrong answer.
    """

    emitted: str
    secret: str
    prefix: str = ""


def surround(secret: str, before: str, after: str) -> str:
    """Place `secret` as a whitespace-delimited token inside free text."""
    return f"{before} {secret} {after}"


@contextmanager
def rules_without(name: str) -> Iterator[None]:
    """Run `redact_text` with one named rule removed.

    `redact_text` reads `REDACTION_RULES` from the module namespace on
    every call, so swapping the tuple here exercises the real function
    rather than a re-implementation of its loop — which is the point,
    since a re-implemented loop would keep passing after the real one
    stopped applying a rule.

    A plain context manager rather than `monkeypatch`, because
    Hypothesis refuses function-scoped fixtures inside `@given` (and is
    right to: the fixture would be set up once and shared across every
    generated example).
    """
    original = logging_module.REDACTION_RULES
    reduced = tuple(rule for rule in original if rule.name != name)
    assert len(reduced) == len(original) - 1, f"no rule named {name!r}"
    logging_module.REDACTION_RULES = reduced  # type: ignore[misc]
    try:
        yield
    finally:
        logging_module.REDACTION_RULES = original  # type: ignore[misc]


# ---------------------------------------------------------------------------
# One secret generator per rule.
#
# Each is bounded so that its secret is caught by *its own* rule and no
# other — bodies stay under the blob rule's forty-character floor, hosts
# stay dotless so the email rule cannot claim a `pw@host` tail. That is
# what makes `test_every_rule_is_load_bearing` a real mutation test
# instead of an accident of overlap.
# ---------------------------------------------------------------------------


@st.composite
def opaque_body(
    draw: st.DrawFn,
    *,
    min_size: int = 16,
    max_size: int = 30,
    alphabet: str = _ALNUM,
) -> str:
    """An alphanumeric run that `_looks_opaque` accepts.

    Built rather than filtered: the prefixed rules require a digit or a
    case change before they will touch a body, which is the whole
    discriminator between `hf_<token>` and `hf_hub_download_cache`, and
    a filter would spend most of its examples being rejected.
    """
    body = draw(st.lists(st.sampled_from(alphabet), min_size=min_size - 2, max_size=max_size - 2))
    body.append(draw(st.sampled_from(string.digits)))
    body.append(draw(st.sampled_from(string.ascii_uppercase)))
    return "".join(draw(st.permutations(body)))


@st.composite
def connection_url_credential(draw: st.DrawFn) -> Credential:
    """A connection string carrying credentials, as ADR 0042's leak did.

    The host is deliberately dotless. With a dot in it the email rule
    would also match the `pw@host.tld` tail and destroy the password —
    correctly, but under the wrong rule, which is exactly the confusion
    the ordering comment in `logging.py` exists to prevent. A dotless
    host leaves `url_userinfo` as the only rule in play, so removing it
    is visible.
    """
    scheme = draw(st.sampled_from(["postgresql", "postgres", "redis", "rediss", "amqp"]))
    user = draw(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12))
    password = draw(st.text(alphabet=_ALNUM + ".", min_size=8, max_size=24))
    host = draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=14))
    port = draw(st.integers(min_value=1, max_value=65535))
    # The assertion is that the password is gone from the output, so
    # nothing else in the URL may spell it back.
    assume(password not in host and password not in user)
    return Credential(f"{scheme}://{user}:{password}@{host}:{port}/db", password)


@st.composite
def bearer_credential(draw: st.DrawFn) -> Credential:
    """An `Authorization` value echoed into a log line."""
    scheme = draw(st.sampled_from(["Bearer", "bearer", "BEARER"]))
    # At least 20 characters, which is the length at which
    # `_redact_bearer` stops asking whether the word after "bearer" is
    # English and treats it as a credential unconditionally; at most 38,
    # so the token cannot also be a forty-character blob.
    token = draw(st.text(alphabet=_BEARER_CHARS, min_size=20, max_size=38))
    assume(not token.startswith("sk-"))
    return Credential(f"{scheme} {token}", token)


@st.composite
def sk_api_key_credential(draw: st.DrawFn) -> Credential:
    """An `sk-` credential of the shape Anthropic and several others issue."""
    body = draw(st.text(alphabet=_TOKEN_CHARS, min_size=8, max_size=30))
    return Credential(f"sk-{body}", body, "sk-")


@st.composite
def environment_scoped_credential(draw: st.DrawFn) -> Credential:
    """`gw_live_…`, `sk_live_…`, `pk_test_…` — the measured gap (WO-C4).

    The issuer half is generated, not sampled from a list, because the
    rule claims to hold for issuers nobody has heard of yet: that is
    the whole reason it is written over the `_live_` / `_test_`
    convention rather than over a vendor registry.
    """
    issuer = draw(
        st.lists(
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=7),
            min_size=1,
            max_size=3,
        ).map("_".join)
    )
    environment = draw(st.sampled_from(["live", "test"]))
    body = draw(opaque_body())
    return Credential(f"{issuer}_{environment}_{body}", body, f"{issuer}_{environment}_")


@st.composite
def vendor_token_credential(draw: st.DrawFn) -> Credential:
    """An issuer-prefixed opaque token: `ghp_…`, `xoxb-…`, `AIza…`.

    Drawn over both registries the module publishes, so a prefix added
    to either one is covered here the moment it lands.
    """
    if draw(st.booleans()):
        prefix = draw(st.sampled_from(_DASHED_VENDOR_TOKEN_PREFIXES))
        body = draw(opaque_body(min_size=16, max_size=26))
        # Slack and GitLab segment their own tokens with `-`. The body
        # must still open and close on an alphanumeric, so the dashes
        # go strictly inside.
        for _ in range(draw(st.integers(min_value=0, max_value=2))):
            cut = draw(st.integers(min_value=1, max_value=len(body) - 1))
            body = f"{body[:cut]}-{body[cut:]}"
    else:
        prefix = draw(st.sampled_from(_VENDOR_TOKEN_PREFIXES))
        body = draw(opaque_body())
    return Credential(f"{prefix}{body}", body, prefix)


@st.composite
def aws_access_key_credential(draw: st.DrawFn) -> Credential:
    """An AWS access key id: four fixed letters, sixteen uppercase."""
    prefix = draw(st.sampled_from(["AKIA", "ASIA", "ABIA", "ACCA"]))
    body = "".join(
        draw(
            st.lists(
                st.sampled_from(string.ascii_uppercase + string.digits),
                min_size=16,
                max_size=16,
            )
        )
    )
    return Credential(f"{prefix}{body}", body, prefix)


@st.composite
def jwt_credential(draw: st.DrawFn) -> Credential:
    """A JWT — a bearer credential travelling without the word "Bearer".

    The signature segment is allowed to be empty, because an `alg:
    none` token is unsigned and is still a credential somebody is
    presenting. Segments stay short enough that no run of them could
    also be a base64 blob.
    """

    def segment(minimum: int) -> str:
        return "".join(
            draw(
                st.lists(
                    st.sampled_from(_BASE64URL_CHARS), min_size=minimum, max_size=30
                )
            )
        )

    token = f"eyJ{segment(10)}.{segment(10)}.{segment(0)}"
    return Credential(token, token)


@st.composite
def email_credential(draw: st.DrawFn) -> Credential:
    """An address in a log line — a person, not a credential, but still PII."""
    local = draw(st.text(alphabet=_ALNUM, min_size=1, max_size=12))
    domain = draw(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10))
    tld = draw(st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=4))
    address = f"{local}@{domain}.{tld}"
    return Credential(address, address)


@st.composite
def base64_blob_credential(draw: st.DrawFn) -> Credential:
    """A base64-ish run long enough, and mixed enough, to be a token.

    Built rather than filtered: `_redact_blob` requires an upper, a
    lower and a digit before it will touch a 40-character run — the
    discriminator between an encoded secret and a long identifier —
    and a filter would spend most of its examples rejecting the
    single-character strings the generator naturally favours.
    """
    body = draw(st.lists(st.sampled_from(_BASE64_CHARS), min_size=37, max_size=77))
    required = [
        draw(st.sampled_from(string.ascii_uppercase)),
        draw(st.sampled_from(string.ascii_lowercase)),
        draw(st.sampled_from(string.digits)),
    ]
    blob = "".join(draw(st.permutations(body + required)))
    return Credential(blob, blob)


#: One generator per rule in `REDACTION_RULES`, keyed by the rule's own
#: name. This mapping is the contract `test_every_rule_has_a_secret_generator`
#: enforces in both directions.
SECRET_GENERATORS: Final[dict[str, st.SearchStrategy[Credential]]] = {
    "url_userinfo": connection_url_credential(),
    "bearer_token": bearer_credential(),
    "sk_api_key": sk_api_key_credential(),
    "environment_scoped_key": environment_scoped_credential(),
    "vendor_prefixed_token": vendor_token_credential(),
    "aws_access_key_id": aws_access_key_credential(),
    "json_web_token": jwt_credential(),
    "email_address": email_credential(),
    "base64_blob": base64_blob_credential(),
}

#: Rules whose replacement deliberately keeps the issuer prefix, mapped
#: to the prefix a redacted example must still show. `sk_api_key` is
#: here too: it has kept `sk-` since ADR 0067 and the reason is the
#: same one.
PREFIX_PRESERVING_RULES: Final[tuple[str, ...]] = (
    "sk_api_key",
    "environment_scoped_key",
    "vendor_prefixed_token",
    "aws_access_key_id",
)


# ---------------------------------------------------------------------------
# The rule set, tested as a set.
# ---------------------------------------------------------------------------


def test_every_rule_has_a_secret_generator() -> None:
    """The generator set and the rule set are the same set.

    Both directions, and each catches a different mistake. A rule with
    no generator is a rule that ships unproven — which is how the
    gateway-credential gap survived ADR 0067 and had to be measured in
    production shapes instead. A generator with no rule is a rule
    someone deleted while leaving its test looking green.
    """
    assert set(SECRET_GENERATORS) == set(RULE_NAMES)


def test_the_rule_names_are_unique() -> None:
    """Names are the test ids and the docs table's keys; duplicates lie.

    Two rules sharing a name would make `rules_without` remove both and
    the parametrised properties run one of them twice, under a report
    that named the other.
    """
    assert len(set(RULE_NAMES)) == len(RULE_NAMES)


@pytest.mark.parametrize("rule_name", RULE_NAMES)
@given(data=st.data(), before=_CONTEXT, after=_CONTEXT)
def test_every_rule_destroys_its_secret(
    rule_name: str, data: st.DataObject, before: str, after: str
) -> None:
    """The one invariant, for every rule there is: the secret is gone."""
    credential = data.draw(SECRET_GENERATORS[rule_name])
    # A secret short enough to also be an ordinary word can appear in
    # the surrounding prose on its own account, and "the secret is not
    # in the output" would then be false for a reason that has nothing
    # to do with redaction.
    assume(credential.secret not in before and credential.secret not in after)

    assert credential.secret not in redact_text(
        surround(credential.emitted, before, after)
    )


@pytest.mark.parametrize("rule_name", RULE_NAMES)
@given(data=st.data(), before=_CONTEXT, after=_CONTEXT)
def test_every_rule_is_load_bearing(
    rule_name: str, data: st.DataObject, before: str, after: str
) -> None:
    """Remove one rule and its secret comes back — the mutation test.

    Written down rather than run by hand, because a rule that is
    redundant with another one is a rule nobody will notice breaking:
    its property keeps passing on the strength of the neighbour, until
    the neighbour is narrowed and both gaps open at once.
    """
    credential = data.draw(SECRET_GENERATORS[rule_name])
    assume(credential.secret not in before and credential.secret not in after)
    line = surround(credential.emitted, before, after)

    with rules_without(rule_name):
        assert credential.secret in redact_text(line)


@pytest.mark.parametrize("rule_name", PREFIX_PRESERVING_RULES)
@given(data=st.data(), before=_CONTEXT, after=_CONTEXT)
def test_a_prefixed_rule_keeps_the_issuer_prefix(
    rule_name: str, data: st.DataObject, before: str, after: str
) -> None:
    """What survives is load-bearing too.

    `ghp_***` tells an operator which console to go and revoke at;
    `***[40 chars]` tells them a secret leaked and leaves them to
    guess. The prefix is published, identical across every token that
    issuer ever minted, and worth exactly as much to an attacker as the
    word "GitHub" — so keeping it costs nothing and buys the whole
    incident response.
    """
    credential = data.draw(SECRET_GENERATORS[rule_name])
    assume(credential.secret not in before and credential.secret not in after)
    assert credential.prefix, f"{rule_name} generator declares no prefix"

    redacted = redact_text(surround(credential.emitted, before, after))

    assert credential.secret not in redacted
    assert f"{credential.prefix}***" in redacted


# ---------------------------------------------------------------------------
# Rule-specific claims: what a rule keeps, not just what it destroys.
# ---------------------------------------------------------------------------


@given(credential=email_credential(), before=_CONTEXT, after=_CONTEXT)
def test_an_email_address_keeps_its_domain(
    credential: Credential, before: str, after: str
) -> None:
    """Only the local part goes; the domain half is kept.

    The domain is the diagnostic half — which mail provider, which
    tenant — and the local part is the personal one, so the rule keeps
    one and drops the other rather than eliding the field.
    """
    redacted = redact_text(surround(credential.emitted, before, after))

    assert credential.secret not in redacted
    assert credential.emitted.split("@", 1)[1] in redacted


@given(credential=connection_url_credential(), before=_CONTEXT, after=_CONTEXT)
def test_a_connection_password_dies_in_both_implementations(
    credential: Credential, before: str, after: str
) -> None:
    """A connection URL's password is gone from free text and from `redact_url`.

    Both paths, in one property, because they are two implementations
    of one promise: `redact_url` parses and is exact, `redact_text`'s
    rule is a regex over prose, and ADR 0042's leak arrived through
    the second one — inside a connection error's message.
    """
    assume(credential.secret not in before and credential.secret not in after)
    host = credential.emitted.partition("@")[2].partition(":")[0]

    assert credential.secret not in redact_text(
        surround(credential.emitted, before, after)
    )
    assert credential.secret not in redact_url(credential.emitted)
    assert host in redact_url(credential.emitted)


# ---------------------------------------------------------------------------
# The other half: legitimate content comes back byte for byte.
#
# Every generator below produces something this system genuinely puts in
# a log line. A rule that eats one of these is worse than the gap it
# closes, because it damages every line rather than one — so these are
# not "nice to have" cases, they are the ceiling on how wide any rule
# above is allowed to be.
# ---------------------------------------------------------------------------


@st.composite
def arxiv_identifier(draw: st.DrawFn) -> str:
    """A paper id, in the four shapes this repository writes it."""
    yymm = f"{draw(st.integers(min_value=7, max_value=99)):02d}"
    yymm += f"{draw(st.integers(min_value=1, max_value=12)):02d}"
    number = f"{draw(st.integers(min_value=1, max_value=99999)):05d}"
    version = draw(st.sampled_from(["", "v1", "v2", "v3", "v11"]))
    identifier = f"{yymm}.{number}{version}"
    return draw(
        st.sampled_from(
            [
                identifier,
                f"arXiv:{identifier}",
                f"https://arxiv.org/abs/{identifier}",
                f"https://arxiv.org/pdf/{identifier}",
            ]
        )
    )


@st.composite
def doi(draw: st.DrawFn) -> str:
    """A DOI, which is a slash, dots and a long opaque-looking suffix."""
    registrant = draw(st.integers(min_value=1000, max_value=99999))
    suffix = draw(
        st.text(alphabet=string.ascii_lowercase + string.digits + ".-", min_size=4, max_size=24)
    )
    return f"10.{registrant}/{suffix}"


@st.composite
def hex_identifier(draw: st.DrawFn) -> str:
    """A span id, trace id, job id or content digest.

    Lowercase hex at the four lengths this system emits: 16 for a span
    id, 32 for a trace or job id, 40 and 64 for digests. These are the
    ids an operator joins on, and the blob rule's mixed-case
    requirement exists precisely so they survive.
    """
    length = draw(st.sampled_from([16, 32, 40, 64]))
    return "".join(draw(st.lists(st.sampled_from(_HEX), min_size=length, max_size=length)))


@st.composite
def uuid_like(draw: st.DrawFn) -> str:
    """A conversation or job UUID in its dashed form."""

    def block(size: int) -> str:
        return "".join(draw(st.lists(st.sampled_from(_HEX), min_size=size, max_size=size)))

    return f"{block(8)}-{block(4)}-4{block(3)}-a{block(3)}-{block(12)}"


@st.composite
def snake_case_identifier(draw: st.DrawFn) -> str:
    """An event name, field name or fixture name.

    `live` and `test` are injected as words on purpose. They are the
    marker the environment-scoped rule keys on, and the narrowing that
    keeps `feature_flag_test_data_loader` out of its jaws — a body of
    unbroken alphanumerics — is only worth having if something asserts
    it.
    """
    words = draw(
        st.lists(
            st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=10),
            min_size=2,
            max_size=5,
        )
    )
    marker = draw(st.sampled_from([None, "live", "test"]))
    if marker is not None:
        words.insert(draw(st.integers(min_value=0, max_value=len(words))), marker)
    return "_".join(words)


@st.composite
def vendor_prefixed_identifier(draw: st.DrawFn) -> str:
    """A legitimate name that opens with a credential prefix.

    `hf_hub_download` and `npm_config_registry` are real, ordinary
    strings, and they are the closest thing the vendor rule has to a
    collision. What keeps them safe is that a snake_case tail never
    reaches sixteen unbroken alphanumerics — so this generator builds
    exactly that and asserts nothing happens to it.
    """
    prefix = draw(st.sampled_from(_VENDOR_TOKEN_PREFIXES + _DASHED_VENDOR_TOKEN_PREFIXES))
    return f"{prefix}{draw(snake_case_identifier())}"


#: Content this system logs and must go on logging. Sampled constants
#: sit beside the generators because some of these are exact strings —
#: the embedding model's name is not a shape, it is a value, and it is
#: one dash away from a token body.
LEGITIMATE_CONTENT: Final[st.SearchStrategy[str]] = st.one_of(
    arxiv_identifier(),
    doi(),
    hex_identifier(),
    uuid_like(),
    snake_case_identifier(),
    vendor_prefixed_identifier(),
    st.sampled_from(
        [
            "claude-sonnet-4-6",
            "claude-opus-4-1-20250805",
            "all-MiniLM-L6-v2",
            "sentence-transformers/all-MiniLM-L6-v2",
            "hf_all-MiniLM-L6-v2",
            "cs.AI/0301001",
            "10.48550/arXiv.2401.00001",
            "LOG_CAPTURE_USER_CONTENT",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
            "STRIPE_LIVE_SECRET_KEY",
            "postgres_pool_opened",
            "redis://redis:6379/0",
            "https://arxiv.org/abs/2401.00001",
            "2026-09-05T14:35:00.123Z",
        ]
    ),
)


@given(content=LEGITIMATE_CONTENT, before=_CONTEXT, after=_CONTEXT)
def test_legitimate_content_survives_byte_for_byte(
    content: str, before: str, after: str
) -> None:
    """The inverse of every property above, and the tighter constraint.

    Recall is cheap: one rule matching `\\S+` would destroy every
    secret in this file. Precision is what a redaction rule is actually
    for, and the way it fails is silent — nobody notices that the paper
    ids stopped appearing until the day they need to join on one.
    """
    line = surround(content, before, after)

    assert redact_text(line) == line


@given(text=st.text(alphabet=string.ascii_lowercase + string.digits + " .,;:()"))
def test_text_with_no_credential_shape_survives_unchanged(text: str) -> None:
    """Ordinary prose comes back byte-for-byte.

    Without this half, `redact_text` could return `"***"` for
    everything and pass every property above. It is also the property
    that a widened rule breaks first: redaction that eats English is
    redaction somebody turns off.
    """
    # The alphabet excludes `@`, `-` and `/`, so the URL, email and
    # `sk-` rules cannot fire on it by construction; "bearer" is the
    # one shape it can still spell, and `_redact_bearer` would be
    # right to act on it.
    assume("bearer" not in text.lower())

    assert redact_text(text) == text


@given(text=st.text(alphabet=_ADVERSARIAL, max_size=160))
def test_redaction_is_idempotent(text: str) -> None:
    """Redacting an already-redacted string changes nothing further.

    The rules run in a fixed order over one string, so each one sees
    the previous rules' replacement markers. Idempotence is the
    statement that those markers are inert: a second pass that found a
    new secret would mean a rule is matching on `***`, `sk-***`,
    `gw_live_***` or `***[jwt]` — that is, on the evidence of
    redaction rather than on a credential.
    """
    once = redact_text(text)

    assert redact_text(once) == once


@given(text=st.text(max_size=160))
def test_redact_url_answers_for_any_string_at_all(text: str) -> None:
    """`redact_url` returns a string for arbitrary input, and never leaks userinfo.

    Its callers hold something they believe is a URL; the belief is
    load-bearing only for the diagnostic value of the result, never
    for whether the call succeeds. Unparseable input is answered with
    `***` — a string that cannot be proven credential-free is not
    passed through.
    """
    redacted = redact_url(text)

    assert isinstance(redacted, str)
    # An `@` may legitimately survive in a path or a query; what may
    # not survive is one in the authority section, which is the only
    # place a credential can sit.
    if redacted != "***":
        authority = redacted.partition("://")[2].partition("/")[0]
        assert "@" not in authority or authority.startswith("***@")


# ---------------------------------------------------------------------------
# The other half of ADR 0067: a principal is hashed, not redacted.
#
# `redact_text` above catches credentials by *shape*. A keystore
# `key_id` has no shape — `internal`, `partner-b`, an operator's own
# handle — so no rule can find one in a string, and the only defence is
# the call site choosing `hash_principal` over the raw value. That makes
# the invariant a property of the call sites, and the two
# admin-migration sweeps are where it was not being kept: both wrote
# `extra={"owner": owner}` into a stream the log layer hashes principals
# into everywhere else.
#
# **The fix under test is WO-A10's, not this work order's.** Both work
# orders were told to fix it and A10's landed first; per the rule that
# two implementations of one fix is worse than either, this file keeps
# only the tests and points them at `principal_hash`, the field name A10
# chose. A10 shipped the fix with the log contract's `owner` removal as
# its guard and no test on the two lines themselves, and the removal
# cannot answer the question these properties ask: the contract test is
# an AST scan of call sites, so it proves the *name* is registered and
# not that the value *arrives*. That distinction is not theoretical here
# — `principal_hash` is a contract field with a precedence rule, fillable
# from `extra` only while nothing has bound one, so "the caller passed
# it" and "the record carries it" are genuinely different claims. These
# assert the second.
# ---------------------------------------------------------------------------

#: Ids an operator can actually hand `--owner`. Shaped like real
#: keystore ids rather than arbitrary text: a generator that produced
#: `"a"` could satisfy a "not in the payload" assertion by accident,
#: since one character appears in almost any string.
PRINCIPAL_IDS = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-_", min_size=6, max_size=24
)

#: The logger both sweeps emit on.
_MIGRATE_LOGGER = "src.api.admin_migrate"


@contextmanager
def _records() -> Iterator[list[logging.LogRecord]]:
    """Collect this logger's records, without `caplog`.

    A plain handler rather than the fixture because `caplog` is
    function-scoped and Hypothesis refuses to reuse a function-scoped
    fixture across generated inputs — correctly, since the records from
    example 1 would still be sitting there for example 2 and the
    absence assertions would be reading the wrong ones.
    """
    logger = logging.getLogger(_MIGRATE_LOGGER)
    collected: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            collected.append(record)

    handler = _Collect(level=logging.INFO)
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Nothing above this logger needs to see these lines, and letting
    # them propagate would run them through the real JSON formatter.
    logger.propagate = False
    try:
        yield collected
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@contextmanager
def _stubbed_postgres() -> Iterator[None]:
    """Stand in for the module `assign_conversation_owner` imports.

    The `UPDATE` itself is `tests/test_admin_migrate.py`'s subject. All
    this file needs is for the function to reach its log line, so the
    cursor reports zero rows and the commit is a no-op.
    """
    cursor = SimpleNamespace(execute=lambda *_a, **_kw: None, rowcount=0)
    connection = SimpleNamespace(cursor=lambda: _entered(cursor), commit=lambda: None)
    module = ModuleType("src.tools.postgres_pool")
    module.init_schema = lambda: None  # type: ignore[attr-defined]
    module._connection = lambda: _entered(connection)  # type: ignore[attr-defined]
    previous = sys.modules.get("src.tools.postgres_pool")
    sys.modules["src.tools.postgres_pool"] = module
    try:
        yield
    finally:
        if previous is None:
            del sys.modules["src.tools.postgres_pool"]
        else:
            sys.modules["src.tools.postgres_pool"] = previous


@contextmanager
def _entered(value: Any) -> Iterator[Any]:
    """`value`, as a context manager that does nothing on the way out."""
    yield value


def _assert_hashed(record: logging.LogRecord, owner: str) -> None:
    """The invariant, stated once for both sweeps.

    Three claims, and each is load-bearing:

    - the digest is *on the record*, not merely passed — the log
      contract's AST scan cannot tell those apart, and `principal_hash`
      is a contract field the formatter will refuse from `extra` if
      anything has bound one;
    - the raw key is not an attribute; and
    - the raw key is nowhere else on the record either, which is what
      catches an id that came back through the message or a second
      field.

    Both directions, because "the id is absent" is satisfiable by
    logging nothing at all, and a sweep nobody can attribute is a sweep
    nobody can audit.
    """
    assert getattr(record, "principal_hash", None) == hash_principal(owner)
    assert not hasattr(record, "owner")
    assert owner not in str(record.__dict__)


@given(owner=PRINCIPAL_IDS)
@hyp_settings(max_examples=40)
def test_the_job_sweep_logs_a_principal_hash_and_never_the_id(owner: str) -> None:
    """`assign_job_owner` names the principal by digest only.

    Driven with an empty row list, which is the shape that isolates the
    question: no row means no Redis call, and the summary line fires
    anyway — it reports the sweep, not the writes. So what is asserted
    is exactly the `extra` payload, with nothing else in the frame able
    to supply or hide the id.
    """
    with _records() as records:
        assert asyncio.run(assign_job_owner(None, [], owner, dry_run=False)) == 0

    assigned = [r for r in records if r.getMessage() == "admin_migrate_jobs_assigned"]
    assert len(assigned) == 1
    _assert_hashed(assigned[0], owner)


@given(owner=PRINCIPAL_IDS)
@hyp_settings(max_examples=40)
def test_the_conversation_sweep_logs_a_principal_hash_and_never_the_id(
    owner: str,
) -> None:
    """The same invariant on the Postgres half of the same tool.

    Two call sites six hundred lines apart, and only one of them being
    fixed is the ordinary way a leak like this survives a review — so
    both are asserted, by the same property.
    """
    with _stubbed_postgres(), _records() as records:
        assign_conversation_owner(owner, dry_run=False)

    assigned = [
        r for r in records if r.getMessage() == "admin_migrate_conversations_assigned"
    ]
    assert len(assigned) == 1
    _assert_hashed(assigned[0], owner)
