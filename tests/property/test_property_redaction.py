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

import asyncio
import logging
import string
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from src.api.admin_migrate import assign_conversation_owner, assign_job_owner
from src.observability import hash_principal, redact_text, redact_url

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
