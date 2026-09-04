"""Invariants of log redaction (ADR 0042, ADR 0067, ADR 0069).

`tests/test_log_redaction.py:25` already writes the property this file
generalises — "the secret is never in the output" — by hand, for six
credentials someone chose. Six is enough to prove a rule runs; it is
not enough to prove a rule *holds*, because the credential that leaks
is by definition the one nobody wrote down.

So each of the five rules gets its own generator here, and each gets
the same one-sentence invariant: the generated secret does not appear
in the redacted string. They are separate tests rather than one
`one_of` because a redaction rule that stops firing should name itself
in the failure.

The other half matters as much. A function that returned `"***"`
unconditionally would satisfy every test above, so
`test_text_with_no_credential_shape_survives_unchanged` asserts the
converse — and idempotence pins the boundary between them, since a
rule that kept finding new secrets in its own output would be
rewriting text it had already cleared.

Every generated secret is placed whitespace-delimited in its
surrounding text. That is not a convenience: four of the five rules
are anchored on a word boundary or a character-class lookbehind, so
`xsk-AKIA...` is deliberately not a match, and a property that ignored
the anchor would be asserting something the rules never claimed.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from src.observability import redact_text, redact_url

pytestmark = [pytest.mark.unit, pytest.mark.property, pytest.mark.security]

#: Words for the text a secret is embedded in. Lowercase letters only,
#: so the context can never itself be mistaken for a credential and
#: make a passing assertion mean nothing.
_CONTEXT = st.lists(
    st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8),
    max_size=8,
).map(" ".join)

_TOKEN_CHARS = string.ascii_letters + string.digits + "_-"
_BEARER_CHARS = string.ascii_letters + string.digits + "-._~+/"
_BASE64_CHARS = string.ascii_letters + string.digits + "+/"
_HOST_CHARS = string.ascii_lowercase + "."

#: The alphabet for the idempotence property: every character any of
#: the five rules keys on, so the generator can build the collisions
#: between them that a hand-written example never would.
_ADVERSARIAL = string.ascii_letters + string.digits + " @:/-._+=~%\n"


def surround(secret: str, before: str, after: str) -> str:
    """Place `secret` as a whitespace-delimited token inside free text."""
    return f"{before} {secret} {after}"


@st.composite
def api_key(draw: st.DrawFn) -> str:
    """An `sk-` credential of the shape Anthropic and several others issue."""
    return "sk-" + draw(
        st.text(alphabet=_TOKEN_CHARS, min_size=8, max_size=40)
    )


@st.composite
def bearer_header(draw: st.DrawFn) -> str:
    """An `Authorization` value echoed into a log line."""
    scheme = draw(st.sampled_from(["Bearer", "bearer", "BEARER"]))
    # At least 20 characters, which is the length at which
    # `_redact_bearer` stops asking whether the word after "bearer" is
    # English and treats it as a credential unconditionally.
    return f"{scheme} " + draw(
        st.text(alphabet=_BEARER_CHARS, min_size=20, max_size=48)
    )


@st.composite
def base64_blob(draw: st.DrawFn) -> str:
    """A base64-ish run long enough, and mixed enough, to be a token.

    Built rather than filtered: `_redact_blob` requires an upper, a
    lower and a digit before it will touch a 40-character run — the
    discriminator between an encoded secret and a long identifier —
    and a filter would spend most of its examples rejecting the
    single-character strings the generator naturally favours.
    """
    body = draw(st.lists(st.sampled_from(_BASE64_CHARS), min_size=37, max_size=77))
    required = [draw(st.sampled_from(string.ascii_uppercase))]
    required.append(draw(st.sampled_from(string.ascii_lowercase)))
    required.append(draw(st.sampled_from(string.digits)))
    return "".join(draw(st.permutations(body + required)))


@st.composite
def email_address(draw: st.DrawFn) -> str:
    """An address in a log line — a person, not a credential, but still PII."""
    local = draw(
        st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=12)
    )
    domain = draw(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10))
    tld = draw(st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=4))
    return f"{local}@{domain}.{tld}"


@st.composite
def connection_url(draw: st.DrawFn) -> tuple[str, str, str]:
    """`(url, password, host)` for a connection string carrying credentials."""
    scheme = draw(st.sampled_from(["postgresql", "postgres", "redis", "rediss"]))
    user = draw(st.text(alphabet=_TOKEN_CHARS, min_size=1, max_size=12))
    password = draw(st.text(alphabet=_TOKEN_CHARS + ".", min_size=8, max_size=24))
    host = draw(st.text(alphabet=_HOST_CHARS, min_size=1, max_size=16))
    port = draw(st.integers(min_value=1, max_value=65535))
    # The assertion is that the password is gone from the output, so
    # the host must not spell it back.
    assume(password not in host)
    return f"{scheme}://{user}:{password}@{host}:{port}/db", password, host


@given(secret=api_key(), before=_CONTEXT, after=_CONTEXT)
def test_an_api_key_never_survives_redaction(
    secret: str, before: str, after: str
) -> None:
    """No generated `sk-` key appears in the redacted text."""
    assert secret not in redact_text(surround(secret, before, after))


@given(secret=bearer_header(), before=_CONTEXT, after=_CONTEXT)
def test_a_bearer_token_never_survives_redaction(
    secret: str, before: str, after: str
) -> None:
    """No generated `Bearer <token>` value appears in the redacted text."""
    assert secret not in redact_text(surround(secret, before, after))


@given(secret=base64_blob(), before=_CONTEXT, after=_CONTEXT)
def test_a_base64_blob_never_survives_redaction(
    secret: str, before: str, after: str
) -> None:
    """No generated base64-ish credential blob appears in the redacted text."""
    assert secret not in redact_text(surround(secret, before, after))


@given(secret=email_address(), before=_CONTEXT, after=_CONTEXT)
def test_an_email_address_never_survives_redaction(
    secret: str, before: str, after: str
) -> None:
    """No generated address survives whole; only its domain half is kept.

    The domain is the diagnostic half — which mail provider, which
    tenant — and the local part is the personal one, so the rule keeps
    one and drops the other rather than eliding the field.
    """
    redacted = redact_text(surround(secret, before, after))

    assert secret not in redacted
    assert secret.split("@", 1)[1] in redacted


@given(url=connection_url(), before=_CONTEXT, after=_CONTEXT)
def test_a_connection_password_never_survives_redaction(
    url: tuple[str, str, str], before: str, after: str
) -> None:
    """A connection URL's password is gone from free text and from `redact_url`.

    Both paths, in one property, because they are two implementations
    of one promise: `redact_url` parses and is exact, `redact_text`'s
    rule is a regex over prose, and ADR 0042's leak arrived through
    the second one — inside a connection error's message.
    """
    connection, password, host = url
    # A password short enough to also be an ordinary word can appear in
    # the surrounding prose on its own account, and "the password is
    # not in the output" would then be false for a reason that has
    # nothing to do with redaction.
    assume(password not in before and password not in after)

    assert password not in redact_text(surround(connection, before, after))
    assert password not in redact_url(connection)
    assert host in redact_url(connection)


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

    The five rules run in a fixed order over one string, so each one
    sees the previous rules' replacement markers. Idempotence is the
    statement that those markers are inert: a second pass that found a
    new secret would mean a rule is matching on `***`, `sk-***` or
    `***[N chars]` — that is, on the evidence of redaction rather than
    on a credential.
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
