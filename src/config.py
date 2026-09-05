"""Typed configuration surface for the project.

Central place to configure every tunable in the workflow. Values load
from environment variables and `.env`, with per-field validation and
type coercion via `pydantic-settings`. Module callers import `settings`
directly:

    from src.config import settings
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_retries=settings.anthropic_max_retries,
    )

Under the production-scale mandate, config lives in one typed surface
so runtime tuning is safe (no string-typed env vars scattered across
call sites) and Deploy-time reviews have one file to audit.

See ADR 0011 for the design rationale (pydantic-settings vs alternatives).

## Overriding for tests

`Settings` is frozen — instances are immutable. Tests that need
different values should either (a) construct a new `Settings(...)`
inline and monkeypatch the module-level `settings` attribute, or (b)
set env vars via `monkeypatch.setenv` before importing.

## Enum-valued fields are `Literal`, not `str`

Every field that selects one of a closed set of implementations
(`job_store`, `conversation_store`, `checkpoint_backend`,
`rate_limit_backend`, `paper_cache`, `embedding_cache`, `log_level`)
is typed `Literal[...]` so a typo'd env var dies at settings load
with pydantic's "unexpected value" message instead of silently
selecting a downstream fallback. See ADR 0046.

## One field may answer to more than one environment variable

`log_capture_user_content` carries a `validation_alias`, because the
OpenTelemetry GenAI conventions define the name of that switch and a
deployment that already sets the conventional name must keep working
whatever this class calls the field. `populate_by_name` is on so
`Settings(log_capture_user_content=True)` still constructs by field
name — the pattern every test in this repository uses.

Aliases are ordered, and the order is precedence: pydantic takes the
*first* name that is present in the environment, so setting the
conventional name to `false` and the repo-local alias to `true` leaves
capture off. That is a narrowing of the "either name being truthy
enables it" rule these flags had while they lived in
`src/observability/logging.py`, and it narrows in the safe direction.

## A secret field is a `SecretStr`

Four fields here hold a value that is *confidential* rather than merely
operational, and the ordinary treatment leaks every one of them.
`log_principal_salt` (WO-C3) was the first; `anthropic_api_key` — the
paid credential — is the second (WO-C4), and it had been sitting
beside the protected salt as a plain `str` since Sprint 1; `api_keys`
and `semantic_scholar_api_key` are the last two (WO-D3). `Settings`
is constructed in some thirty test modules and pydantic's `__repr__`
prints every field, so a plain `str` puts the value into any
traceback, `-vv` assertion diff or settings dump that ever touched an
instance. For the salt that turns the whole point of `principal_hash`
(ADR 0067: a key id that never reaches the log stream) back into a
dictionary attack over a word list; for the key it is the credential
itself.

The log layer does redact an `sk-`-shaped string on the way out
(`redact_text`), but that is a shape rule, not a type rule: it catches
an Anthropic key and misses a gateway or proxy credential that does
not carry the prefix, and it only fires on text that reached the
redacting formatter in the first place. Masking at the type is the
rule that does not depend on either.

`SecretStr` renders as `**********` in `repr`, `str`, `model_dump()`
and `model_dump_json()`, and hands over the real value only through
`get_secret_value()`. The rule for any future secret field is the same
one `src/observability/context.py` and `src/llm.py` follow: call
`get_secret_value()` once, at the point of use, and never let the
wrapper itself reach a string — an f-string of a `SecretStr`
interpolates the mask, which for the salt would salt the entire fleet
with `**********` and agree with itself everywhere while matching
nobody's key id, and for the key would authenticate as `**********`.

The last two moved in WO-D3, and ADR 0067 was right that neither was
a one-line retype. `api_keys` is the *inbound* keystore: one string
carrying every secret the deployment accepts, which
`src/api/auth.py::parse_api_keys` splits into the `{secret:
principal}` map every request is authenticated against. It unwraps
once, at the top of the parse, and the entries it refuses no longer
echo the offending text — an entry with no `:` separator is a bare
secret, and quoting it into a startup `ValueError` put it wherever
that error went next. `semantic_scholar_api_key` is an *outbound*
credential that `src/tools/semantic_scholar.py::_headers` puts on the
wire; its old `if settings.semantic_scholar_api_key:` was exactly the
emptiness check `src/llm.py` warns about — correct today, but only
via pydantic's `__len__` — so it now tests the unwrapped local. The
keystore *map* keeps plain `str` secrets on purpose: it is a
process-local dict that `hmac.compare_digest` reads as bytes, it is
built identically by `load_keystore_from_file` from a JSON file, and
`ApiKeyPrincipal` deliberately retains no raw key.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The OpenTelemetry GenAI conventions' content-capture flag, and the
#: only opt-in environment variable those conventions define. The spec
#: says instrumentations "SHOULD NOT capture [message content] by
#: default, but SHOULD provide an option for users to opt in" — this is
#: that option, under the name the standard already gave it, so an
#: operator who has made the content decision once does not have to
#: discover a second switch to make it stick in a second sink.
#:
#: Declared here rather than in `src/observability/logging.py` because
#: it is now a pydantic alias: the string the field answers to and the
#: string the resolver re-reads have to be the same string, or a
#: live flip would silently disagree with the configured value.
CONTENT_CAPTURE_ENV: Final = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"

#: A repo-local second name for the same field. It predates the
#: conventional one and is kept so no deployment has to change; it is
#: second in the alias order, so the conventional name wins when both
#: are set.
CONTENT_CAPTURE_ENV_ALIAS: Final = "LOG_CAPTURE_USER_CONTENT"

#: The head-sampling ratio's environment variable. Identical to the
#: upper-cased field name — named as a constant only so
#: `src/observability/tracing.py` and the tests can refer to it without
#: repeating the literal.
TRACE_SAMPLE_RATIO_ENV: Final = "TRACE_SAMPLE_RATIO"

#: The principal salt's environment variable. Identical to the
#: upper-cased field name, like `TRACE_SAMPLE_RATIO` above, and named
#: for the same reason: `src/observability/context.py` re-exports this
#: constant and the tests set it, so the variable an operator exports
#: and the field that reads it are one string and cannot drift.
PRINCIPAL_SALT_ENV: Final = "LOG_PRINCIPAL_SALT"

#: The string tokens pydantic itself accepts for a `bool` field, split
#: by which way they decide. Written out rather than delegated back to
#: pydantic because `content_capture_enabled()` re-reads the
#: environment on every call — once per content key per log record —
#: and has to reach the same verdict this class reached at load.
#: `tests/test_config.py` pins both sets against pydantic's own
#: coercion, so a release that widens the grammar shows up as a failing
#: assertion rather than as a flag that stops working.
BOOL_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"1", "on", "t", "true", "y", "yes"})
BOOL_FALSE_TOKENS: Final[frozenset[str]] = frozenset(
    {"0", "off", "f", "false", "n", "no"}
)


def parse_bool_flag(value: str) -> bool | None:
    """Read an environment-shaped string as a boolean, or `None`.

    The one grammar behind the content-capture switch, used both by the
    field validator below and by
    `src.observability.logging.content_capture_enabled`, which re-reads
    the same variables live. Two callers, one grammar, so a live flip
    cannot disagree with the value the process booted with.

    Args:
        value: The raw environment string.

    Returns:
        `True` or `False` for anything in the token sets above, `False`
        for a blank — `LOG_CAPTURE_USER_CONTENT=` is how a Compose file
        and a `.env` both spell "I am not setting this" — and `None`
        for a string that is not a boolean at all.
    """
    token = value.strip().lower()
    if not token:
        return False
    if token in BOOL_TRUE_TOKENS:
        return True
    if token in BOOL_FALSE_TOKENS:
        return False
    return None


class Settings(BaseSettings):
    """All runtime tunables for the arxiv research agent.

    Fields group by concern (Anthropic, search, reader, chunker, critic,
    logging) and map to `SCREAMING_SNAKE_CASE` environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        # `log_capture_user_content` has a `validation_alias`, which on
        # its own would make the field *only* settable by alias and
        # break every `Settings(field_name=...)` call in the suite.
        populate_by_name=True,
    )

    # ------ Anthropic / LLM --------------------------------------------
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Claude API key — the paid credential, and a `SecretStr` "
            "since WO-C4 for the same reason `log_principal_salt` is "
            "one: pydantic prints every field in a repr, so a plain "
            "`str` put the live key into any `Settings` repr, dump or "
            "`-vv` assertion diff. The raw value is read exactly once, "
            "by `src/llm.py`, through `get_secret_value()`. Empty is "
            "the default and means 'not configured': `src/llm.py` "
            "refuses to construct a client rather than calling with a "
            "blank key. It is *not* how a run is made free — the "
            "zero-spend sentinel `local-preview-disabled` is "
            "deliberately non-empty (`tests/conftest.py`), so the key "
            "stays truthy, the client constructor is still reached, "
            "and the spend guard fires there instead of being hidden "
            "behind a 'not configured' error."
        ),
    )

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_api_key_is_unset(cls, value: Any) -> Any:
        """Treat a whitespace-only key as unset rather than as a key.

        The same rule `_blank_salt_is_unset` applies below, for the
        same reason: `SecretStr` accepts any string, so without this an
        `ANTHROPIC_API_KEY=" "` — a Compose file whose interpolation
        produced a blank, a shell that quoted an empty variable — would
        be a *configured* key. It is truthy, so `src/llm.py` would
        build a live client with it and the operator's answer would be
        a 401 from Anthropic rather than the one-line "not set in .env"
        this repository already knows how to say.

        A non-blank value is passed through *unstripped*, exactly as
        the salt is: the bytes an operator exported are the bytes that
        authenticate, and quietly trimming a credential is a change of
        behaviour dressed as hygiene.
        """
        return "" if isinstance(value, str) and not value.strip() else value

    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        description="Model ID used by every agent unless overridden per-call",
    )
    anthropic_max_retries: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Retries after the first attempt on 408/409/429/5xx",
    )
    anthropic_timeout_sec: float = Field(
        default=120.0,
        gt=0.0,
        le=600.0,
        description="Per-request timeout; must be below SDK's 600s default",
    )

    # ------ Search -----------------------------------------------------
    use_mock_data: bool = Field(
        default=False,
        description="Force built-in mock papers instead of hitting arXiv",
    )
    max_papers: int = Field(default=10, ge=1, le=50, description="Cap on ranked paper count")
    results_per_query: int = Field(
        default=5,
        ge=1,
        le=20,
        description="arXiv results fetched per sub-question search",
    )

    # ------ Reader -----------------------------------------------------
    reader_max_workers: int = Field(
        default=5,
        ge=1,
        le=20,
        description="ThreadPool workers for per-paper LLM calls",
    )
    reader_max_chunks_per_paper: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Top-K ranked chunks fed to Claude per paper",
    )

    # ------ Chunker ----------------------------------------------------
    chunker_max_tokens: int = Field(
        default=800, ge=100, le=4000, description="Target chunk token budget"
    )
    chunker_overlap_tokens: int = Field(
        default=100,
        ge=0,
        le=500,
        description="Overlap between consecutive chunks in a section",
    )

    # ------ Critic -----------------------------------------------------
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Hard cap on critic-driven revision loops",
    )

    # ------ Logging ----------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description=(
            "Standard-library logging level name. Literal so a typo "
            "(`LOG_LEVEL=DEBG`) fails at settings load instead of "
            "surfacing as a `logging` error at first emission. See "
            "ADR 0046."
        ),
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        """Uppercase before Literal validation.

        `LOG_LEVEL=debug` has always worked because the logging setup
        calls `.upper()` at use; keep that contract now that the field
        is a case-sensitive `Literal`.
        """
        return value.upper() if isinstance(value, str) else value

    log_capture_user_content: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            CONTENT_CAPTURE_ENV, CONTENT_CAPTURE_ENV_ALIAS
        ),
        description=(
            "Let user content — research queries, report bodies, paper "
            "text, learner writing — stay in the log stream and on "
            "spans instead of being replaced with `[redacted: N "
            "chars]`. Off by default, which is what the OpenTelemetry "
            "GenAI conventions require of an instrumentation: content "
            "capture is opt-in, never a default. Answers to two "
            "environment variables — the conventional "
            "`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` "
            "first, then the older repo-local "
            "`LOG_CAPTURE_USER_CONTENT` — so a deployment that already "
            "set either one keeps working. Both switch logs *and* "
            "spans: it is one content decision, not two. Turning it on "
            "also restores the report body to the failed-terminal-write "
            "line, which is how a lost success used to be recoverable; "
            "off is the default because the exposure outweighs the "
            "recovery. Unlike every other field here it may also be "
            "flipped without a restart — see "
            "`src.observability.logging.content_capture_enabled`. See "
            "ADR 0067."
        ),
    )

    @field_validator("log_capture_user_content", mode="before")
    @classmethod
    def _parse_capture_flag(cls, value: Any) -> Any:
        """Apply `parse_bool_flag`, and name both variables on a refusal.

        Two jobs pydantic's own `bool` parser does not do here. A blank
        has to stay "off" rather than becoming a boot failure, because
        `LOG_CAPTURE_USER_CONTENT=` is how a Compose file spells
        "unset" and the resolver this field replaces read it that way.
        And the error has to name the variable the operator actually
        set: pydantic reports the *first* alias whichever one supplied
        the value, so a typo in `LOG_CAPTURE_USER_CONTENT` would
        otherwise arrive as a complaint about
        `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` — a
        variable that operator has never heard of.

        Raises:
            ValueError: When the value is a string that is not a
                boolean in any spelling pydantic accepts.
        """
        if not isinstance(value, str):
            return value
        parsed = parse_bool_flag(value)
        if parsed is None:
            raise ValueError(
                f"content capture must be true or false; got {value!r}. "
                f"Set {CONTENT_CAPTURE_ENV} or {CONTENT_CAPTURE_ENV_ALIAS} "
                f"to one of {sorted(BOOL_TRUE_TOKENS)} or "
                f"{sorted(BOOL_FALSE_TOKENS)}, or leave both unset for the "
                "default (off)."
            )
        return parsed

    log_principal_salt: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Deployment-wide salt for `principal_hash` — the salted "
            "digest ADR 0067 puts on every log line in place of the API "
            "key id itself. Set the same value on every process and a "
            "principal's lines join across containers and hosts; leave "
            "it unset (the default) and each process invents its own at "
            "import, so grouping still works *within* a process and "
            "`src.observability.principal_salt_is_ephemeral()` reports "
            "which of the two you have. Unsalted is not one of the "
            "options: key ids are short operator-chosen strings and a "
            "bare digest of one is recoverable from a word list. A "
            "blank value means unset, not a salt — `LOG_PRINCIPAL_SALT=` "
            "is how a Compose file spells \"I am not setting this\", and "
            "it takes the per-process branch rather than salting the "
            "fleet with the empty string. A secret, and one of the two "
            "fields here that are (`anthropic_api_key` is the other): "
            "it is a `SecretStr`, so it cannot reach a repr or a dump, "
            "and the raw value is read exactly once, by "
            "`src/observability/context.py`, through "
            "`get_secret_value()`."
        ),
    )

    @field_validator("log_principal_salt", mode="before")
    @classmethod
    def _blank_salt_is_unset(cls, value: Any) -> Any:
        """Treat a blank salt as unset rather than as a salt.

        The same rule `_parse_capture_flag` and
        `_blank_sample_ratio_is_unset` apply, and it matters more here:
        `SecretStr` accepts any string, so without this a stray
        `LOG_PRINCIPAL_SALT="   "` would be a configured fleet-wide
        salt that no other host reproduces, and
        `principal_salt_is_ephemeral()` would report it as configured
        while the joins it promises silently failed.

        A non-blank value is passed through *unstripped*: the digest of
        a configured salt has to stay byte-for-byte what it was before
        this field existed, or an upgrade would renumber every
        `principal_hash` in the fleet.
        """
        return "" if isinstance(value, str) and not value.strip() else value

    # ------ HTTP retry (arXiv API + PDF downloads) ---------------------
    http_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Retries on 429/5xx for arXiv API and PDF downloads",
    )
    http_backoff_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="urllib3 Retry backoff_factor (delay = factor * 2**attempt)",
    )
    pdf_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024 * 1024,
        le=500 * 1024 * 1024,
        description=(
            "Hard cap on a single PDF download. Reader streams bytes "
            "and aborts once the cap is reached so a 500MB adversarial "
            "PDF can't OOM the process. See ADR 0033."
        ),
    )
    pdf_download_timeout_sec: float = Field(
        default=60.0,
        gt=0.0,
        le=300.0,
        description=(
            "Per-attempt timeout on one PDF fetch. ADR 0068's follow-up "
            "4: this was the last hardcoded timeout in the codebase "
            "(`pdf_parser.DOWNLOAD_TIMEOUT_SEC = 60`), and a timeout "
            "nothing declares is a timeout no clamp can see — the retry "
            "envelope is trimmed against `(retries + 1) * timeout`, "
            "which needs the attempt cost stated. The value is "
            "unchanged from the constant, so the per-attempt behaviour "
            "is what it always was; what changes is that at 60s only "
            "two attempts fit `api_job_timeout_sec * "
            "http_call_chain_budget_fraction`, so retries are trimmed "
            "to 1 and `retry_envelope_clamped` says so once per "
            "process. Larger than `arxiv_timeout_sec` because a PDF is "
            "megabytes where an Atom feed is kilobytes."
        ),
    )

    # ------ Resilience (Phase A, ADR 0068) ----------------------------
    # Retry amplification is the measured problem: three retries at five
    # levels of a stack is 243x load on a dependency that is already
    # failing. The knobs below bound *retries* rather than requests, so
    # a healthy deployment behaves exactly as it did without them.
    enable_retry_budget: bool = Field(
        default=True,
        description=(
            "Throttle retries through a per-process token bucket once a "
            "dependency starts failing (ADR 0068). Off restores the "
            "pre-budget behaviour exactly: every request pays its full "
            "retry envelope. A kill switch, not a tuning knob."
        ),
    )
    retry_budget_capacity: int = Field(
        default=100,
        ge=1,
        le=100000,
        description=(
            "Retries one worker may spend against one dependency before "
            "the budget starts refusing them. Per process, not per "
            "fleet: N workers allow N x this, which is deliberate — a "
            "shared budget would have to ask Redis for permission "
            "during the outage it exists for."
        ),
    )
    retry_budget_refill_per_sec: float = Field(
        default=1.0,
        gt=0.0,
        le=1000.0,
        description=(
            "Retries returned to the budget per second. Must be > 0: it "
            "is the only refill a fully drained bucket can earn, since "
            "the success refund needs successes the outage is denying."
        ),
    )
    retry_budget_success_refund: float = Field(
        default=0.2,
        gt=0.0,
        le=1.0,
        description=(
            "Retries earned per successful call. 0.2 means five "
            "successes buy one retry, matching the AWS SDKs' 5:1 "
            "ratio — the budget tracks the retry/success ratio rather "
            "than the absolute retry rate."
        ),
    )
    http_backoff_max_sec: float = Field(
        default=20.0,
        gt=0.0,
        le=600.0,
        description=(
            "Ceiling on one HTTP backoff, and the cap in the Full "
            "Jitter draw `random(0, min(cap, base * 2**attempt))`. "
            "urllib3's own default is 120s, which is a fifth of the "
            "default job budget spent asleep."
        ),
    )
    http_call_chain_budget_fraction: float = Field(
        default=0.25,
        gt=0.0,
        le=1.0,
        description=(
            "Share of `api_job_timeout_sec` one HTTP call chain may "
            "occupy in the worst case. `src/llm.py` gives the model "
            "0.75 because a job is mostly model calls; HTTP is the "
            "smaller half of a run, and a search node issues up to 12 "
            "requests inside one job. Retries are trimmed against it, "
            "never the per-attempt timeout."
        ),
    )
    arxiv_timeout_sec: float = Field(
        default=25.0,
        gt=0.0,
        le=300.0,
        description=(
            "Per-attempt timeout on an arXiv Atom API request. Chosen "
            "from a false-timeout rate rather than a round number: this "
            "deployment accepts abandoning the slowest ~0.1% of arXiv "
            "responses (p99.9) and pays for the rest. The distribution "
            "is not yet measured here, so 25s is a declared target and "
            "ADR 0068 names the measurement that replaces it; the "
            "previous hardcoded 30 was neither declared nor tunable."
        ),
    )
    arxiv_pacing_sec: float = Field(
        default=3.0,
        ge=0.0,
        le=60.0,
        description=(
            "Pause between consecutive live arXiv queries in one run. "
            "arXiv asks API clients to space requests; 3s is the value "
            "this repository has always used, now tunable and now "
            "interruptible by a job cancel (ADR 0068)."
        ),
    )
    redis_connect_timeout_sec: float = Field(
        default=5.0,
        gt=0.0,
        le=120.0,
        description=(
            "TCP connect timeout for the Redis client. A same-host or "
            "same-network Redis connects in under a millisecond, so 5s "
            "is generous enough to survive one SYN retransmit and short "
            "enough that an unreachable Redis fails a request instead "
            "of hanging it. Unset before ADR 0068, which is why "
            "`create_app` had to wrap one call in `asyncio.wait_for`."
        ),
    )
    redis_socket_timeout_sec: float = Field(
        default=5.0,
        gt=0.0,
        le=300.0,
        description=(
            "Per-command read/write timeout for the Redis client. "
            "Every command this service issues is O(1) or a bounded "
            "SCAN batch. Pub/sub is unaffected: redis-py passes "
            "`math.inf` for blocking `listen()` reads precisely so a "
            "socket timeout cannot end an idle SSE subscription."
        ),
    )
    redis_health_check_interval_sec: int = Field(
        default=30,
        ge=0,
        le=3600,
        description=(
            "How often a pooled Redis connection PINGs before reuse. "
            "Closes the stale-connection window a load balancer or an "
            "idle-timeout proxy opens; 0 disables the check."
        ),
    )
    redis_max_retries: int = Field(
        default=1,
        ge=0,
        le=10,
        description=(
            "Retries redis-py itself makes on a timeout or connection "
            "error, with Full Jitter backoff. Redis is the one owning "
            "level for Redis retries (ADR 0068) — no application loop "
            "may add a second."
        ),
    )
    job_redrive_max_attempts: int = Field(
        default=3,
        ge=1,
        le=100,
        description=(
            "Requeues one job may receive before the redriver "
            "dead-letters it as `internal_dead_letter` instead of "
            "putting it back in flight. Without this bound an enabled "
            "`job_redrive_requeue_pending` is a poison-message loop: a "
            "job that reliably kills its worker is requeued by the "
            "next sweep forever. See ADR 0068."
        ),
    )

    # ------ API auth + rate limiting (ADR 0033) ------------------------
    enable_api_auth: bool = Field(
        default=False,
        description=(
            "Gate every /research and /conversations route behind the "
            "X-API-Key header. Off by default so local dev + eval + "
            "existing tests keep working. Turn on for any exposed "
            "deployment: without it, an anonymous caller can drive "
            "the workflow at ANTHROPIC_API_KEY's expense. ADR 0033."
        ),
    )
    api_keys: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Comma-separated `name:key` pairs used when "
            "`enable_api_auth` is on. Example: "
            "`internal:sk_a123,partner:sk_b456`. Names appear in "
            "logs; the raw key is compared with `hmac.compare_digest` "
            "so lookups run in constant time. A `SecretStr` since "
            "WO-D3, and the highest-value one here: a single string "
            "holding *every* inbound secret the deployment accepts, "
            "so a plain `str` put the whole keystore into any "
            "`Settings` repr, dump or `-vv` assertion diff at once. "
            "`src/api/auth.py::parse_api_keys` is the only reader and "
            "takes the raw value once, through `get_secret_value()`. "
            "This field is read once "
            "at app startup, so rotating through it requires a restart; "
            "set `api_keys_file` for hot reload instead (ADR 0037)."
        ),
    )

    @field_validator("api_keys", mode="before")
    @classmethod
    def _blank_api_keys_are_unset(cls, value: Any) -> Any:
        """Treat a whitespace-only keystore as unset rather than as one.

        The rule `_blank_api_key_is_unset` and `_blank_salt_is_unset`
        apply, for a reason particular to this field:
        `deploy/pilot/compose.pilot.yml` sets `API_KEYS: ""`
        deliberately, to say "the file is the keystore, not the
        string" (ADR 0037). `parse_api_keys` has always ignored empty
        entries, so a blank parsed to `{}` before this retype and
        still does; what the validator adds is that the *wrapper* is
        falsy for a blank too, so anything that asks the field rather
        than the parse gets the same answer the parse would give.

        A non-blank value passes through *unstripped*, as the other
        three secrets do. `parse_api_keys` strips each entry itself,
        and a second invisible pass over a credential string here
        would be a behaviour change dressed as hygiene.
        """
        return "" if isinstance(value, str) and not value.strip() else value
    api_key_hourly_limit: int = Field(
        default=100,
        ge=1,
        le=100_000,
        description=(
            "Per-API-key ceiling on `POST /research` submits per "
            "sliding hour. Correct across workers under "
            "`rate_limit_backend=redis`; per-worker under `memory`."
        ),
    )
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "Backend for the per-key rate limiter. `memory` (default) "
            "is single-process — under multi-worker uvicorn the "
            "effective limit becomes `api_key_hourly_limit * n_workers`. "
            "`redis` uses a shared ZSET on `ratelimit:{key_id}`; "
            "requires `job_store=redis` — the limiter reuses the "
            "RedisJobStore's client rather than opening a second pool "
            "from `redis_url`, and startup fails without one. See "
            "ADR 0037."
        ),
    )
    api_keys_file: str = Field(
        default="",
        description=(
            "Optional path to a JSON file `{name: secret, ...}` used "
            "as the keystore. When set, overrides `api_keys` and "
            "enables hot reload — a background task polls mtime "
            "every `api_keys_reload_interval_sec` and swaps the "
            "in-memory keystore on change without a restart. See "
            "ADR 0037."
        ),
    )
    api_keys_reload_interval_sec: int = Field(
        default=30,
        ge=1,
        le=3600,
        description=(
            "Poll interval for the hot-reload keystore watcher. "
            "Lower = faster propagation, more disk stats. Ignored "
            "when `api_keys_file` is empty."
        ),
    )
    api_cors_allow_origins: str = Field(
        default="",
        description=(
            "Comma-separated origins allowed by CORS. Empty (default) "
            "installs no CORS middleware — same-origin only. Set to "
            "`*` for full permissive (dev only); production should "
            "list explicit origins, e.g. "
            "`https://arxiv-agent.example.com,https://staging...`."
        ),
    )

    # ------ HTTP API (Sprint 4) ---------------------------------------
    # Tunables for the FastAPI surface layered on top of the workflow.
    # See ADR 0025.
    api_host: str = Field(
        default="127.0.0.1",
        description=(
            "Bind address for `python -m src.api.serve`. Use 0.0.0.0 in "
            "a container so the port is reachable from outside."
        ),
    )
    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Bind port for `python -m src.api.serve`",
    )
    api_max_concurrent_jobs: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "Semaphore-limited ceiling on concurrent workflow runs per "
            "API process. Each uvicorn worker holds its own semaphore, "
            "so a multi-worker deployment admits up to n_workers times "
            "this many jobs in flight."
        ),
    )
    api_job_timeout_sec: int = Field(
        default=600,
        ge=10,
        le=3600,
        description=(
            "Hard timeout applied to a single workflow invocation via "
            "the API. Jobs exceeding this are marked failed with "
            "`timeout` error type. Independent of the client's HTTP "
            "read timeout on the streaming endpoint."
        ),
    )
    api_job_drain_timeout_sec: int = Field(
        default=30,
        ge=1,
        le=300,
        description=(
            "How long the runner holds a job's concurrency permit after "
            "a timeout or shutdown, waiting for the graph node's thread "
            "to actually return. A node thread cannot be killed, so the "
            "permit has to outlive the cancelled coroutine or "
            "`api_max_concurrent_jobs` stops bounding real work. Past "
            "this budget the runner gives up, logs "
            "`api_job_node_drain_expired`, and the abandoned thread is "
            "counted into `/healthz`'s `active_jobs` until it returns. "
            "The shutdown path caps this further at "
            "`runner.SHUTDOWN_DRAIN_SEC`, so raising this cannot push "
            "SIGTERM past the container's grace period. See ADR 0047."
        ),
    )
    api_job_retention_sec: int = Field(
        default=86400,
        ge=60,
        le=86400,
        description=(
            "How long a completed job's record + result stays queryable "
            "before it's evicted. In-memory: age check on evict_older_than; "
            "Redis: TTL on the job key. Same knob honored by both stores. "
            "Default is 24h, not 1h: the job row is the only durable copy "
            "of a report unless the caller exports it or attached a "
            "conversation, so an aggressive TTL silently destroys results."
        ),
    )
    api_sse_heartbeat_sec: float = Field(
        default=15.0,
        gt=0.0,
        le=300.0,
        description=(
            "Idle interval between SSE keepalive comment frames on "
            "`GET /research/{id}/stream`. Must stay comfortably under "
            "the shortest idle timeout of any proxy in front of the "
            "app (nginx `proxy_read_timeout` defaults to 60s). See "
            "ADR 0038."
        ),
    )
    api_sse_max_duration_sec: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description=(
            "Ceiling on how long a single SSE connection stays open. "
            "A stream on a job that never reaches a terminal state "
            "would otherwise pin a worker connection forever; at the "
            "deadline the server emits `stream_timeout` and closes so "
            "the client can reconnect. See ADR 0038."
        ),
    )
    enable_hitl: bool = Field(
        default=True,
        description=(
            "When true, the workflow interrupts after the planner so a "
            "human can review + edit the plan (sub_questions, "
            "search_queries) before search runs. See ADR 0030. Per-query "
            "bypass via `POST /research { hitl_bypass: true }` — the eval "
            "runner uses that path so nightly benchmarks don't stall."
        ),
    )
    api_hitl_timeout_sec: int = Field(
        default=1800,
        ge=30,
        le=86400,
        description=(
            "How long a job sits in `pending_review` before the runner "
            "gives up and marks it failed with error_type=hitl_timeout. "
            "Independent of `api_job_timeout_sec`, which caps only the "
            "workflow's own wall-clock (not the human's decision time)."
        ),
    )
    job_store: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "Which JobStore implementation the API uses. `memory` = "
            "in-process InMemoryJobStore (single-worker only, jobs die "
            "with the process). `redis` = RedisJobStore backed by "
            "`redis_url`, safe for horizontal API scaling. See ADR 0027."
        ),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description=(
            "Async Redis URL used by `RedisJobStore` when `job_store=redis`. "
            "In compose the default is `redis://redis:6379/0`."
        ),
    )

    # ------ Job redriver + worker leases (ADR 0038) -------------------
    # A worker that dies mid-job leaves its Redis row stuck in a
    # non-terminal status forever: `GET /research/{id}` reports
    # `running` and the SSE stream hangs waiting for a terminal frame
    # that nobody will ever publish. The lease is what distinguishes
    # "orphaned" from "running on a worker that is still alive", so a
    # rolling restart of worker 3 does not reap worker 1's jobs.
    enable_job_redriver: bool = Field(
        default=True,
        description=(
            "Run the startup reconciliation sweep that reclaims jobs "
            "orphaned by a dead worker. No-op unless `job_store=redis` "
            "(nothing survives a restart under the in-memory store). "
            "See ADR 0038."
        ),
    )
    job_lease_ttl_sec: int = Field(
        default=90,
        ge=10,
        le=3600,
        description=(
            "TTL on `joblease:{job_id}`, the key a worker holds while "
            "it runs a job. Expiry is what marks the job orphaned, so "
            "this is also the worst-case delay before a crashed "
            "worker's jobs become reclaimable. Must be > "
            "`job_lease_refresh_sec` with margin for a GC pause."
        ),
    )
    job_lease_refresh_sec: int = Field(
        default=30,
        ge=5,
        le=1800,
        description=(
            "How often the runner's background task re-expires its "
            "job lease. Keep at roughly a third of `job_lease_ttl_sec` "
            "so two consecutive missed refreshes still do not orphan a "
            "healthy job."
        ),
    )
    job_redrive_requeue_pending: bool = Field(
        default=False,
        description=(
            "When true, orphaned jobs still in `pending` (accepted but "
            "never started, so no partial work and no spend) are "
            "resubmitted instead of failed. `running` and parked "
            "(`pending_review`, `awaiting_learner`) jobs are always "
            "failed with `error_type=orphaned` — resuming them would "
            "double-charge for LLM calls already made."
        ),
    )
    job_redrive_max_scan: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description=(
            "Upper bound on job keys examined in one redrive sweep, so "
            "a huge keyspace cannot stall startup. Hitting the cap is "
            "logged as `job_redriver_scan_capped` rather than silently "
            "truncating the sweep."
        ),
    )
    job_redrive_interval_sec: int = Field(
        default=300,
        ge=30,
        le=86400,
        description=(
            "Interval for the periodic redrive sweep. The startup "
            "sweep alone misses a real case: a container restarted "
            "before its old lease expires sees the job as live at "
            "boot, and no later sweep ever runs — the row stays "
            "`running` forever. Periodic sweeps close that. Only "
            "meaningful when `enable_job_redriver` is on and the "
            "store is Redis."
        ),
    )

    # ------ Learning sessions (Phase W, WO-W01, ADR 0057) -------------
    # The `session` job kind is turn-shaped: it parks in
    # `awaiting_learner` between turns the same way a research job
    # parks in `pending_review`, so it needs the same two bounds the
    # HITL parking has — how long one wait may last, and how many
    # waits one job may accumulate before the runner concludes the
    # graph and the runner disagree structurally. No flag lives here:
    # WO-W01 ships the lifecycle only, and the capability flags
    # (`enable_session_loop` and the rest of the Phase W ladder) land
    # with the graph that needs them.
    session_turn_timeout_sec: int = Field(
        default=1800,
        ge=30,
        le=86400,
        description=(
            "How long a `session` job sits in `awaiting_learner` "
            "before the runner gives up and marks it failed with "
            "error_type=session_turn_timeout. The learner-facing "
            "mirror of `api_hitl_timeout_sec`, and separate from it "
            "because the two wait on different humans doing different "
            "things: a reviewer resolving one plan, versus a learner "
            "reading a passage and answering."
        ),
    )
    session_max_turns: int = Field(
        default=40,
        ge=1,
        le=500,
        description=(
            "Upper bound on learner turns in one session job. The "
            "research path bounds its resume loop with "
            "`max_iterations + 2` because only its first interrupt is "
            "a human review; a session parks on every turn, so it "
            "needs its own ceiling. Overrunning it fails the job "
            "loudly rather than reporting a paused graph as finished. "
            "Also sizes the job's outer wall-clock allowance "
            "(`session_max_turns * session_turn_timeout_sec` on top of "
            "`api_job_timeout_sec`), so raising it lengthens the "
            "backstop a wedged session takes to die."
        ),
    )

    # ------ Postgres (paper cache + embedding cache) ------------------
    # Wired up in ADR 0028. Empty URL = feature disabled: the
    # paper cache falls back to on-disk `.cache/pdfs/` (Sprint 1
    # behavior, byte-identical), and the embedding cache is a no-op.
    postgres_url: str = Field(
        default="",
        description=(
            "libpq-style Postgres URL (`postgresql://user:pass@host/db`) "
            "for the paper cache + embedding cache. Empty = disabled, "
            "falls back to on-disk paper cache and no embedding cache. "
            "In compose the default is "
            "`postgresql://arxiv:arxiv@postgres:5432/arxiv`."
        ),
    )
    paper_cache: Literal["disk", "postgres"] = Field(
        default="disk",
        description=(
            "PaperCache implementation. `disk` (default) = "
            "`.cache/pdfs/<key>.txt` per Sprint 1; `postgres` = "
            "PostgresPaperCache backed by `postgres_url`. See ADR 0028."
        ),
    )
    embedding_cache: Literal["none", "postgres"] = Field(
        default="none",
        description=(
            "EmbeddingCache implementation. `none` (default) preserves "
            "Sprint 1 behavior byte-identically — every call re-encodes "
            "via MiniLM. `postgres` skips MiniLM inference for texts "
            "we've seen before, indexed by content hash + model name. "
            "See ADR 0028."
        ),
    )
    embedding_device: Literal["cpu", "auto", "mps", "cuda"] = Field(
        default="cpu",
        description=(
            "Device for the sentence-transformers embedding model. "
            "`cpu` (default) is deliberate: MiniLM encodes are small "
            "enough that CPU latency is negligible, while the torch "
            "MPS backend has segfaulted inside the Metal driver under "
            "concurrent processes — a native crash kills the worker "
            "with no traceback. `auto` restores the library's own "
            "device pick for deployments that want GPU encode."
        ),
    )
    conversation_store: Literal["memory", "postgres"] = Field(
        default="memory",
        description=(
            "ConversationStore implementation. `memory` = in-process "
            "InMemoryConversationStore (single-worker only, dies with "
            "the process). `postgres` = PostgresConversationStore, "
            "durable across restarts + shared across workers. See ADR "
            "0032. Compose sets this to `postgres` alongside the "
            "paper + embedding caches."
        ),
    )
    conversation_context_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "How many prior-report chunks the retriever pulls into the "
            "planner's system prompt when a job runs in a conversation. "
            "Higher = more continuity, more tokens; lower = leaner, may "
            "lose thread. See ADR 0032."
        ),
    )

    # ------ Checkpointing ---------------------------------------------
    enable_checkpointing: bool = Field(
        default=True,
        description="Persist LangGraph state for interrupt/resume",
    )
    checkpoint_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        description=(
            "Backend for LangGraph checkpoints. `sqlite` uses "
            "`checkpoint_db_path` — single-writer, per-worker only. "
            "`postgres` shares checkpoints across API workers via "
            "`postgres_url`; required for multi-worker HITL and "
            "horizontal scaling. See ADR 0034."
        ),
    )
    checkpoint_db_path: str = Field(
        default=".cache/checkpoints.sqlite",
        description="SQLite file used when `checkpoint_backend=sqlite`",
    )

    # ------ Telemetry (OpenTelemetry: tracing + metrics) ---------------
    enable_tracing: bool = Field(
        default=False,
        description="Emit OpenTelemetry spans around each agent node",
    )
    enable_metrics: bool = Field(
        default=False,
        description=(
            "Emit OpenTelemetry metrics (job counts + durations, LLM "
            "cost/calls, concurrency gauges, rate-limit rejections). "
            "Off by default and gated exactly like `enable_tracing`: "
            "with it off no meter provider is installed and every "
            "record point returns on a single `None` check. Shares "
            "`otel_exporter_endpoint` with tracing — one collector "
            "receives both signals. See ADR 0049."
        ),
    )
    otel_service_name: str = Field(
        default="arxiv-research-agent",
        description="OTel `service.name` resource attribute",
    )
    otel_exporter_endpoint: str = Field(
        default="",
        description=("OTLP HTTP endpoint (e.g. http://localhost:4318). Empty = console exporter."),
    )
    otel_metric_export_interval_sec: int = Field(
        default=60,
        ge=1,
        le=3600,
        description=(
            "How often the periodic metric reader exports to the OTLP "
            "collector. Bounded (ADR 0046): below 1s the export thread "
            "costs more than the signal is worth, and above an hour a "
            "worker that dies takes its last window's counters with it."
        ),
    )
    trace_sample_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Head-sampling ratio: 0.1 keeps one trace in ten. `None` — "
            "the default, and what an unset or empty "
            "`TRACE_SAMPLE_RATIO` means — installs no sampler at all, "
            "which leaves the SDK's own `OTEL_TRACES_SAMPLER` / "
            "`OTEL_TRACES_SAMPLER_ARG` handling intact so an operator "
            "already using the standard variables is not silently "
            "overridden by a repository default. Bounded rather than "
            "clamped (ADR 0046): `TRACE_SAMPLE_RATIO=10` from someone "
            "who meant 10% used to be quietly rounded to 1.0 and "
            "sample *everything*, which is a bill. The sampler is "
            "always parent-based, so a worker never re-decides for a "
            "job whose submitting request was already sampled. See "
            "ADR 0066."
        ),
    )

    @field_validator("trace_sample_ratio", mode="before")
    @classmethod
    def _blank_sample_ratio_is_unset(cls, value: Any) -> Any:
        """Treat an empty value as "install no sampler".

        Same reason `_parse_capture_flag` reads a blank as off:
        `float("")` is a `ValidationError`, and `TRACE_SAMPLE_RATIO=` is
        how a Compose file spells "leave this alone". It has always
        meant "no sampler", and it still does.
        """
        return None if isinstance(value, str) and not value.strip() else value

    # ------ Evaluation integrity (Phase A, ADR 0070) ------------------
    eval_judge_model: str = Field(
        default="claude-sonnet-4-6",
        min_length=1,
        description=(
            "Model every LLM-as-judge metric is scored with. A model id "
            "in its own right, NOT a per-agent override: the empty "
            "string is rejected rather than falling back to "
            "`anthropic_model`, because that fallback is the defect ADR "
            "0070 closes — the judges passed no model, so upgrading the "
            "product model silently changed the grader and the system "
            "graded itself with a moving ruler. Changing this value "
            "invalidates every existing baseline: a regression diff "
            "across a judge swap compares two different instruments."
        ),
    )
    eval_seed: int = Field(
        default=0,
        ge=0,
        description=(
            "Seed applied to the harness's own random generators at the "
            "start of a campaign, and recorded on every summary row. It "
            "pins what this process draws locally; it does NOT make a "
            "campaign reproducible, because the Messages API exposes no "
            "sampling seed and the judges are sampled. Recorded so a row "
            "can say what was pinned rather than implying a determinism "
            "nobody has. See ADR 0070."
        ),
    )

    # ------ Supervisor loop (Sprint 2) --------------------------------
    enable_supervisor: bool = Field(
        default=False,
        description=(
            "Use the supervisor loop instead of the fixed pipeline. Off by "
            "default so behavior stays stable; flip on to run the agentic path."
        ),
    )
    min_quality_score: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Supervisor stops when critic quality_score >= this",
    )
    max_cost_usd: float = Field(
        default=2.00,
        gt=0.0,
        le=100.0,
        description=(
            "Per-run LLM spend ceiling in USD. Enforced by the API "
            "runner between graph nodes (both fixed-DAG and supervisor "
            "shapes) — see ADR 0033. The supervisor also checks this "
            "independently as a stop condition."
        ),
    )
    learning_session_max_cost_usd: float = Field(
        default=0.50,
        gt=0.0,
        le=25.0,
        description=(
            "Per-session LLM spend ceiling. Bound as the effective cost cap "
            "for session jobs only; research jobs continue to use max_cost_usd."
        ),
    )
    learning_session_cost_cap_behavior: Literal["refuse", "degraded_close"] = Field(
        default="refuse",
        description=(
            "Session behavior after the LLM choke point refuses a call at the "
            "cost ceiling. refuse = terminal failure; degraded_close = honest "
            "successful close with no further model output."
        ),
    )
    max_loop_iterations: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Hard cap on supervisor invocations per run — orthogonal to "
            "`max_iterations` (critic-revision cap). Prevents thrash."
        ),
    )
    enable_verifier: bool = Field(
        default=False,
        description=(
            "Adds `verify` to the supervisor's action space. Independent "
            "of `enable_supervisor` so the two can be A/B'd separately "
            "against the Sprint 1 baseline. Verifier is a no-op under "
            "the fixed pipeline. See ADR 0015."
        ),
    )
    enable_evidence_store: bool = Field(
        default=False,
        description=(
            "Reader also emits `EvidenceClaim`s traced to ranked chunks; "
            "verifier judges against `source_text` instead of abstracts. "
            "Independent of `enable_supervisor` / `enable_verifier` so "
            "the substrate upgrade can be A/B'd separately. Fixed "
            "pipeline stays unchanged. See ADR 0016."
        ),
    )
    reader_max_claims_per_paper: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Cap on claims the reader extracts per paper when the "
            "evidence store is enabled. Bounds prompt cost."
        ),
    )
    enable_query_refiner: bool = Field(
        default=False,
        description=(
            "Adds `refine_query` to the supervisor's action space. "
            "Without it, the supervisor's 'search again' choice re-runs "
            "the same failing queries. Independent of other Sprint 2 "
            "flags. No-op under the fixed pipeline. See ADR 0018."
        ),
    )
    query_refiner_max_queries: int = Field(
        default=5,
        ge=1,
        le=15,
        description=(
            "Cap on new queries the refiner emits per invocation. "
            "Bounds fan-out on the next search round."
        ),
    )
    enable_reader_recovery: bool = Field(
        default=False,
        description=(
            "Reader emits `analysis_complete` / `missing_context` / "
            "`request_more_sections` so the supervisor can re-invoke "
            "it with a narrower brief. On re-invocation, the ranker "
            "reserves slots for chunks from the requested sections. "
            "Independent of other Sprint 2 flags. Fixed pipeline "
            "unchanged. See ADR 0019."
        ),
    )
    enable_prompt_isolation: bool = Field(
        default=False,
        description=(
            "Wrap PDF-derived text in untrusted-content tags in reader "
            "prompts and sanitize reader control-field outputs. "
            "Recommended whenever `enable_supervisor` is on because "
            "supervisor routing now consumes reader-emitted control "
            "signals derived from arXiv text. Default off to preserve "
            "Sprint 1 baseline byte-for-byte. See ADR 0020."
        ),
    )

    # ------ Per-agent model routing (ADR 0021, Sprint 3) --------------
    # Each field defaults to "" — empty means "fall back to
    # anthropic_model". Set to a Claude model ID to route a specific
    # agent's calls to a cheaper (Haiku) or richer (Opus) tier.
    # See ADR 0021 for the recommended defaults and cost impact.
    reader_model: str = Field(
        default="",
        description=(
            "Model for the reader's per-paper analysis calls. Highest-"
            "volume agent (one call per paper); Haiku is the "
            "recommended override. Empty falls back to anthropic_model."
        ),
    )
    planner_model: str = Field(
        default="",
        description="Model for the planner. Empty falls back to anthropic_model.",
    )
    synthesizer_model: str = Field(
        default="",
        description=(
            "Model for the synthesizer's report generation. Writing "
            "quality benefits from the base model; overrides only if "
            "you need to trade quality for cost. Empty = anthropic_model."
        ),
    )
    critic_model: str = Field(
        default="",
        description=(
            "Model for the critic's quality judgment. Empty falls back to anthropic_model."
        ),
    )
    verifier_model: str = Field(
        default="",
        description=(
            "Model for the runtime faithfulness verifier. Empty falls back to anthropic_model."
        ),
    )
    supervisor_model: str = Field(
        default="",
        description=(
            "Model for the supervisor's per-turn routing decision. "
            "High-volume under a full loop (~1 call per action); Haiku "
            "is the recommended override. Empty = anthropic_model."
        ),
    )
    query_refiner_model: str = Field(
        default="",
        description=(
            "Model for the query refiner. Short generation task; Haiku "
            "is the recommended override. Empty = anthropic_model."
        ),
    )
    tutor_model: str = Field(
        default="",
        description=(
            "Model for guided-read check-in and tutor turns. Empty falls "
            "back to anthropic_model; a cheaper model is expected for the "
            "high-volume turn path, with quality measured by WO-W09/W10."
        ),
    )
    assessment_model: str = Field(
        default="",
        description=(
            "Model for the one-shot explain-back assessment judge. Empty "
            "falls back to anthropic_model. Outputs remain tutor guidance "
            "until the WO-W09 calibration prior is owner-ratified."
        ),
    )

    # ------ Prompt caching (ADR 0022, Sprint 3) -----------------------
    enable_prompt_caching: bool = Field(
        default=False,
        description=(
            "Mark each agent's system prompt for Anthropic's ephemeral "
            "prompt cache. Reads on cache hits bill at 10% of the input "
            "rate; writes bill at 125% (25% first-write premium). Best "
            "hit rate on the reader (parallel fan-out) and supervisor "
            "(loop iterations). Default off — preserves Sprint 1 "
            "baseline byte-identical. See ADR 0022."
        ),
    )

    # ------ Semantic Scholar (ADR 0023, Sprint 3) ---------------------
    enable_semantic_scholar: bool = Field(
        default=False,
        description=(
            "Enrich arXiv search results with Semantic Scholar's "
            "citation graph. Search agent fetches one-hop references "
            "for the top-K arXiv seed papers and unions them with the "
            "arXiv set before ranking. Broader retrieval (conferences, "
            "journals) + related work discovery via cited papers. "
            "Default off preserves Sprint 1 baseline. See ADR 0023."
        ),
    )
    semantic_scholar_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Optional Semantic Scholar API key. Unset = anonymous rate "
            "limit (~100 req / 5 min per IP); set = 1 req/sec sustained. "
            "A `SecretStr` since WO-D3, like every other credential "
            "here: `src/tools/semantic_scholar.py::_headers` is the "
            "only reader and takes the raw value once, straight into "
            "the `x-api-key` header, so it reaches the wire and "
            "nothing else — not a log line, not a span attribute, not "
            "the `str(exc)` that adapter puts on a failed request."
        ),
    )

    @field_validator("semantic_scholar_api_key", mode="before")
    @classmethod
    def _blank_semantic_scholar_key_is_unset(cls, value: Any) -> Any:
        """Treat a whitespace-only key as unset rather than as a key.

        The same rule as the other three secrets, and here it decides
        whether enrichment works at all: `_headers` sends the header
        when the key is set and omits it when it is not, so a stray
        `SEMANTIC_SCHOLAR_API_KEY=" "` would put `x-api-key: " "` on
        every S2 request. Semantic Scholar answers a bad key with a
        403, so the whole enrichment path would fail closed rather
        than falling back to the anonymous rate limit it is designed
        to fall back to — and `_get_json` swallows that as a warning,
        so the operator's symptom is silently empty enrichment.

        A non-blank value passes through *unstripped*: the bytes an
        operator exported are the bytes that authenticate.
        """
        return "" if isinstance(value, str) and not value.strip() else value
    semantic_scholar_seed_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "How many top-ranked arXiv papers to expand via S2 "
            "references. Zero disables enrichment even with the flag "
            "on. Bounds outbound S2 API calls per run."
        ),
    )
    semantic_scholar_refs_per_seed: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "How many references to fetch per seed paper (one-hop). "
            "Total S2 references per run bounded at "
            "`seed_count * refs_per_seed`."
        ),
    )
    semantic_scholar_timeout_sec: float = Field(
        default=30.0,
        gt=0.0,
        le=120.0,
        description="Per-request timeout for S2 API calls.",
    )

    # ------ Learner profile (Phase W, WO-W02, ADR 0058) ----------------
    # Comment-fenced so the Phase W merge queue can order every card's
    # config edit without a textual collision
    # (planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md §5.4).
    enable_learner_profile: bool = Field(
        default=False,
        description=(
            "Mount the per-learner profile store and the "
            "`GET/PUT/DELETE /learn/profile` endpoints. Off by default; "
            "the routes answer 404 `learner_profile_disabled` while it "
            "is off, so every existing surface is unchanged. Requires "
            "`enable_api_auth` — the profile is keyed by the "
            "authenticated principal and has no meaning for an "
            "anonymous caller, so loading the two out of step is a "
            "startup error rather than a runtime surprise. Until MT-01 "
            "lands this is honest only for single-human / pilot "
            "deployments, where keys are issued fresh per person and "
            "never reassigned. See ADR 0058. WO-W07 shares this gate: "
            "`GET /learn/progress` answers the same 404 while it is off, "
            "so the flag mounts the whole learner surface rather than "
            "the profile alone."
        ),
    )
    learner_profile_store: Literal["memory", "postgres"] = Field(
        default="memory",
        description=(
            "ProfileStore implementation, mirroring `conversation_store`. "
            "`memory` = in-process, single-worker, dies with the "
            "process. `postgres` = durable + shared across workers on "
            "the ADR 0028 pool. Any deployment that actually carries "
            "learners wants `postgres`: a profile that evaporates on "
            "restart makes the deletion promise meaningless in the "
            "other direction too. See ADR 0058."
        ),
    )

    @model_validator(mode="after")
    def _check_learner_profile_requires_auth(self) -> Settings:
        """Refuse a learner profile with no principal to key it on.

        01 §1.3 makes `enable_api_auth` a hard dependency of
        `enable_learner_profile`: without it every caller is the
        anonymous principal, and a per-learner record shared by
        everyone is not a per-learner record. Both flags have valid
        individual values that combine into a broken pair, so the
        check belongs here rather than on either field. Failing at
        settings load means the operator sees it before traffic,
        instead of discovering it as a 404 per request.

        Raises:
            ValueError: When the profile is enabled without auth.
        """
        if self.enable_learner_profile and not self.enable_api_auth:
            raise ValueError(
                "enable_learner_profile requires enable_api_auth=true: the "
                "profile is keyed by the authenticated principal and "
                "refuses the anonymous one. See ADR 0058 and "
                "planning/07-learning-platform/01-LEARNING-AGENT.md §1.3."
            )
        return self

    # ------ Progress ledger (Phase W, WO-W07) --------------------------
    # Own fenced section, appended after WO-W02's per 05 §5.4. The flag
    # this endpoint is gated on is `enable_learner_profile` above —
    # declared once, by WO-W02, and carrying the validator that refuses
    # it without `enable_api_auth`. `progress_event_store` is WO-W07's
    # alone.
    progress_event_store: Literal["memory", "postgres"] = Field(
        default="memory",
        description=(
            "ProgressEventStore implementation for the append-only "
            "learner ledger (01 §4.4). `memory` = in-process, dies with "
            "the process — fine for tests and single-worker local dev. "
            "`postgres` = the `progress_events` table, durable and "
            "shared across workers, where the append-only trigger and "
            "the no-mastery-scalar CHECK actually bite. Mirrors "
            "`conversation_store`'s shape (ADR 0032)."
        ),
    )

    # ------ Learning content (Phase W, WO-W15) -------------------------
    # Comment-fenced like the section above, so the Phase W merge queue
    # can order every card's config edit without a textual collision
    # (planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md §5.4).
    enable_learn_content: bool = Field(
        default=False,
        description=(
            "Serve the repo-shipped learning-path manifests over "
            "`GET /learn/paths` and `GET /learn/paths/{path_id}`. Read "
            "only: the endpoints hold no store, take no writes, and "
            "return published, human-reviewed entries exclusively. Off "
            "by default like every Phase W capability — with it off the "
            "routes exist and answer 404 `learn_content_disabled`, which "
            "is the honest report that this deployment publishes no "
            "content. See planning/07-learning-platform/02-CONTENT.md."
        ),
    )
    learn_content_root: str = Field(
        default="",
        description=(
            "Directory holding `paths/<path_id>/path.json`. Empty (the "
            "default) resolves to the `content/` directory shipped beside "
            "`src/` in the repo and in the image. Set it only to serve a "
            "content tree from outside the image."
        ),
    )

    # ------ Guided-read sessions (Phase W, WO-W03) -------------------
    enable_session_loop: bool = Field(
        default=False,
        description=(
            "Mount POST/GET /learn/sessions and learner-turn resume. Off by "
            "default. Requires the principal-scoped learner profile and "
            "LangGraph checkpointing because every turn parks and resumes "
            "from durable state. See 01-LEARNING-AGENT.md §5.4."
        ),
    )
    enable_assessment_judge: bool = Field(
        default=False,
        description=(
            "Run the one-shot explain-back judge inside guided-read sessions. "
            "Off by default; requires enable_session_loop. Off preserves the "
            "informal recorded-ungraded close. See ADR 0060."
        ),
    )

    @model_validator(mode="after")
    def _check_session_loop_dependencies(self) -> Settings:
        if self.enable_session_loop and not self.enable_learner_profile:
            raise ValueError(
                "enable_session_loop requires enable_learner_profile=true: "
                "the session graph reads a principal-scoped Tier-1 profile."
            )
        if self.enable_session_loop and not self.enable_checkpointing:
            raise ValueError(
                "enable_session_loop requires enable_checkpointing=true: "
                "learner turns resume from LangGraph checkpoints."
            )
        if self.enable_assessment_judge and not self.enable_session_loop:
            raise ValueError(
                "enable_assessment_judge requires enable_session_loop=true: "
                "the judge only consumes a guided session explain-back."
            )
        return self

    @model_validator(mode="after")
    def _check_lease_invariant(self) -> Settings:
        """Reject a lease TTL a refresh cycle cannot keep alive.

        `job_lease_refresh_sec`'s own description promises that "two
        consecutive missed refreshes still do not orphan a healthy
        job" — which only holds while three refresh cycles fit inside
        `job_lease_ttl_sec`. Below that margin a healthy job loses its
        lease on an ordinary GC pause and a peer's redrive sweep
        reclaims work that is still running. Both fields have
        individually valid ranges that combine into a broken pair, so
        the check has to live here rather than on either Field.

        Raises:
            ValueError: When the refresh interval leaves no margin.
        """
        if self.job_lease_refresh_sec * 3 > self.job_lease_ttl_sec:
            raise ValueError(
                "job_lease_refresh_sec must be at most a third of "
                f"job_lease_ttl_sec so two missed refreshes are "
                f"survivable; got refresh={self.job_lease_refresh_sec} "
                f"ttl={self.job_lease_ttl_sec}. See ADR 0038."
            )
        return self

    @model_validator(mode="after")
    def _check_chunker_budget_invariant(self) -> Settings:
        """Reject an overlap the chunk budget cannot contain.

        `_split_by_budget` advances its window with
        `start = max(start + 1, end - overlap_chars)`. Once the overlap
        reaches the budget, `end - overlap_chars` never gets past
        `start`, the `max` floor takes over, and the loop emits roughly
        one chunk per *character* — a paper becomes tens of thousands of
        chunks, each of which is ranked and some of which are sent to a
        model. That is a bill and a timeout, not an error message.

        Same shape as `_check_lease_invariant` above and for the same
        reason: `chunker_overlap_tokens` (0-500) and
        `chunker_max_tokens` (100-4000) each validate fine on their own,
        so `overlap=500` with `max=100` passes both Fields and is only
        wrong as a pair. `tests/property/test_property_chunker.py`
        already had to draw its budgets as a coupled pair to keep out of
        the degradation, and ADR 0069 recorded it as a configuration
        hazard; this turns the hazard into a load-time refusal.

        Raises:
            ValueError: When the overlap is not strictly under the
                budget.
        """
        if self.chunker_overlap_tokens >= self.chunker_max_tokens:
            raise ValueError(
                "chunker_overlap_tokens must be strictly less than "
                "chunker_max_tokens, or the chunker emits one chunk per "
                f"character; got overlap={self.chunker_overlap_tokens} "
                f"max={self.chunker_max_tokens}. See ADR 0069."
            )
        return self

    # ------ Agent capability (CAP-02) ---------------------------------
    # One versioned selector for the research policy, as
    # `docs/agent-engineering/07-first-policy-experiment.md` §4 asks for
    # ("Do not add these as ad hoc Boolean combinations"). The arms of
    # that experiment stay expressed the way they already are — A, B and
    # D are `ENABLE_SUPERVISOR` / `ENABLE_EVIDENCE_STORE` /
    # `ENABLE_VERIFIER` — and arm C, which no combination of those three
    # produces, becomes a value of this field. See ADR 0076.
    research_policy: Literal["legacy", "fixed_verify_repair"] = Field(
        default="legacy",
        description=(
            "Which research graph `build_workflow` compiles. `legacy` "
            "(default) derives the shape from `enable_supervisor` exactly "
            "as before. `fixed_verify_repair` compiles the arm-C graph: "
            "planner -> search -> reader -> synthesizer -> verify, one "
            "bounded repair on a failed verdict, then re-verification "
            "before the critic. It requires enable_supervisor=false, "
            "enable_evidence_store=true and enable_verifier=false; any "
            "other combination is refused at load. See ADR 0076."
        ),
    )

    @model_validator(mode="after")
    def _check_research_policy_requirements(self) -> Settings:
        """Refuse a `research_policy` its companion flags contradict.

        The point of the refusal is the experiment's, not the graph's.
        Arm C is defined as the *fixed evidence path plus verification
        and repair*; a run that called itself `fixed_verify_repair` while
        the supervisor owned routing, or while the reader emitted no
        evidence, would be labelled C in the manifest and be something
        else on the wire. That mislabelling is what
        `docs/agent-engineering/12-p0-work-orders.md` §11 asks W05 to
        make impossible, and a load-time refusal is the only place it can
        be made impossible without a live run to inspect.

        `enable_verifier` is refused rather than ignored for the same
        reason: it names the *supervisor's* verify action (ADR 0015), so
        leaving it on would put two different verifiers in one run's
        configuration with nothing to say which one a result came from.

        Raises:
            ValueError: When any of the three companion flags carries a
                value arm C does not permit. The message names every
                offending flag rather than only the first, so one boot
                attempt is enough to fix the whole environment file.
        """
        if self.research_policy != "fixed_verify_repair":
            return self
        problems: list[str] = []
        if self.enable_supervisor:
            problems.append(
                "enable_supervisor must be false (arm C is a fixed policy; "
                "the supervisor loop is arm D)"
            )
        if not self.enable_evidence_store:
            problems.append(
                "enable_evidence_store must be true (the verify node judges "
                "claims against the reader's source chunks)"
            )
        if self.enable_verifier:
            problems.append(
                "enable_verifier must be false (that flag adds the "
                "supervisor's verify action, which this policy replaces with "
                "its own verify node)"
            )
        if problems:
            raise ValueError(
                "research_policy=fixed_verify_repair requires a specific flag "
                "combination and got another: " + "; ".join(problems)
                + ". See ADR 0076."
            )
        return self

    # ------ Agent capability (CAP-01) ---------------------------------
    #
    # Model-aware request profiles (ADR 0076). Every field here defaults
    # to what the gateway already did, so a deployment that sets none of
    # them sends the byte-identical request body
    # `tests/test_llm_request_golden.py` pins.
    #
    # What each one becomes, and when: `llm_thinking` becomes
    # `thinking={"type": "adaptive"}`, `llm_effort` becomes
    # `output_config={"effort": ...}`, `llm_temperature` becomes
    # `temperature`, and `enable_structured_outputs` becomes
    # `output_config={"format": ...}` — each only when
    # `src/llm_models.py` says the *resolved* model accepts it.

    llm_thinking: Literal["off", "adaptive"] = Field(
        default="off",
        description=(
            "Adaptive thinking on every model call. `adaptive` sends "
            "`thinking={'type': 'adaptive'}` and lets the model decide "
            "how much to think; `off` (the default) sends no thinking "
            "field, which is what the gateway has always done. Refused "
            "at load when any routed model's capability row lacks "
            "adaptive thinking, because that combination is an HTTP 400 "
            "on every call rather than a degraded one. Turning it on "
            "changes the judges' requests too — they share this gateway "
            "— which re-baselines every eval metric under ADR 0070. "
            "See ADR 0076."
        ),
    )
    llm_effort: Literal["", "low", "medium", "high", "xhigh", "max"] = Field(
        default="",
        description=(
            "Default `output_config.effort` for every call. Empty (the "
            "default) sends no effort field, which the API reads as "
            "`high`. Set it to trade thoroughness against token spend "
            "inside one model. Refused at load when a routed model's "
            "row does not list the level — Haiku 4.5 rejects effort "
            "outright and Sonnet 4.6 has no `xhigh`. See ADR 0076."
        ),
    )

    # Per-agent effort overrides, mirroring the `<agent>_model` fields
    # above. Empty inherits `llm_effort`; `off` sends no effort for that
    # agent, which is the only way to route one agent to a model that
    # rejects effort (Haiku, which is ADR 0021's reader recommendation)
    # while the rest of the deployment runs at a global level.
    planner_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the planner. Empty inherits llm_effort; "
            "'off' sends no effort field."
        ),
    )
    reader_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the reader's per-paper analysis. Empty inherits "
            "llm_effort; 'off' sends no effort field."
        ),
    )
    synthesizer_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the synthesizer. Empty inherits llm_effort; "
            "'off' sends no effort field."
        ),
    )
    critic_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the critic. Empty inherits llm_effort; "
            "'off' sends no effort field."
        ),
    )
    verifier_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the verifier. Empty inherits llm_effort; "
            "'off' sends no effort field."
        ),
    )
    supervisor_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the supervisor's routing call. Empty inherits "
            "llm_effort; 'off' sends no effort field."
        ),
    )
    query_refiner_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the query refiner. Empty inherits llm_effort; "
            "'off' sends no effort field."
        ),
    )
    tutor_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for guided-read tutor turns. Empty inherits "
            "llm_effort; 'off' sends no effort field."
        ),
    )
    assessment_effort: Literal[
        "", "off", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        default="",
        description=(
            "Effort for the explain-back assessment judge. Empty "
            "inherits llm_effort; 'off' sends no effort field."
        ),
    )

    enable_structured_outputs: bool = Field(
        default=False,
        description=(
            "Ask the model for JSON that satisfies a schema instead of "
            "parsing free text with `json.loads`. Applies only where a "
            "caller passes a schema and the resolved model's row allows "
            "it; everywhere else the existing parse path runs unchanged. "
            "Unlike thinking and effort this is *not* refused at load on "
            "an unsupporting model, because it has a working fallback "
            "and they do not. Default off preserves the Sprint 1 "
            "baseline. See ADR 0076."
        ),
    )
    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Sampling temperature, sent only to models whose capability "
            "row accepts sampling parameters. 0.3 is the constant the "
            "gateway hard-coded before ADR 0076, so the default changes "
            "nothing. On a model that rejects sampling (Opus 4.7+, Opus "
            "5, Sonnet 5, Fable/Mythos) it is silently not sent — which "
            "is the fix, not a regression: sending it there is an HTTP "
            "400 on every call."
        ),
    )

    def effort_for(self, agent: str = "") -> str:
        """The effort level to send for `agent`, or `""` to send none.

        Args:
            agent: One of `EFFORT_AGENTS`, or `""` for a call that
                carries no agent identity and therefore takes the
                deployment-wide `llm_effort`.

        Returns:
            An effort level, or `""` meaning "send no effort field".
            `"off"` on the per-agent field resolves to `""` — the two
            spellings differ only in the field, where `""` inherits and
            `"off"` opts out.
        """
        if not agent:
            return self.llm_effort
        override: str = getattr(self, f"{agent}_effort")
        if override == "off":
            return ""
        return override or self.llm_effort

    def model_for(self, agent: str = "") -> str:
        """The model id `agent`'s calls resolve to.

        The `override or base` rule `resolved_model_ids` derives the
        billable set with, in one place, so the effort validation below
        and the gateway agree on which model an agent's effort has to be
        legal for.
        """
        if not agent:
            return self.anthropic_model
        override: str = getattr(self, f"{agent}_model")
        return override or self.anthropic_model

    def _models_effort_applies_to(self, agent: str) -> set[str]:
        """Every model id the effort resolved for `agent` would reach.

        For a named agent that is one model. For the deployment-wide
        `llm_effort` it is every routed id that does *not* carry an
        override of its own — including `eval_judge_model`, which is a
        routed id in its own right (ADR 0070) and would receive the
        global effort like any other call.
        """
        if agent:
            return {self.model_for(agent)}
        overridden = {
            self.model_for(name)
            for name in EFFORT_AGENTS
            if getattr(self, f"{name}_effort")
        }
        return _routed_model_ids(self) - overridden

    @model_validator(mode="after")
    def _check_request_profile_is_supported(self) -> Settings:
        """Refuse a request feature the configured models would 400 on.

        Thinking and effort are checked here, at load, because neither
        has a good runtime answer: sending `thinking` to a model with no
        adaptive mode, or an effort level it does not list, fails the
        call with an HTTP 400 — every call, on every node, for the whole
        deployment. A configuration that cannot make one successful
        request should not start.

        `enable_structured_outputs` and `llm_temperature` are
        deliberately *not* checked. Both degrade: an unsupported model
        does not receive them and the call runs exactly as it did before
        ADR 0076. Refusing to boot over a feature that has a working
        fallback would make this check indistinguishable from a
        strictness preference.

        `src.llm_models` is imported inside the method rather than at
        module scope because it logs through `src.observability`, which
        imports this module — a top-level import would close the cycle
        while this module's body is still executing.

        Raises:
            ValueError: Naming the field, the model, and what that model
                does accept.
        """
        from src.llm_models import capabilities_for

        if self.llm_thinking == "adaptive":
            for model in sorted(_routed_model_ids(self)):
                if not capabilities_for(model).adaptive_thinking:
                    raise ValueError(
                        "llm_thinking='adaptive' is not supported by the "
                        f"routed model {model!r}, which answers a request "
                        "carrying `thinking` with an HTTP 400. Set "
                        "LLM_THINKING=off, or route that agent to a model "
                        "with adaptive thinking. See ADR 0076."
                    )

        for agent in ("", *EFFORT_AGENTS):
            level = self.effort_for(agent)
            if not level:
                continue
            field = f"{agent}_effort" if agent else "llm_effort"
            for model in sorted(self._models_effort_applies_to(agent)):
                caps = capabilities_for(model)
                if caps.supports_effort(level):
                    continue
                accepted = (
                    ", ".join(sorted(caps.effort_levels))
                    if caps.effort_levels
                    else "none — this model rejects output_config.effort"
                )
                remedy = (
                    f"Set {field.upper()}=off to exempt that agent"
                    if agent
                    else (
                        "Clear LLM_EFFORT, or set <AGENT>_EFFORT=off for "
                        "each agent routed to this model"
                    )
                )
                raise ValueError(
                    f"{field}={level!r} is not supported by the routed "
                    f"model {model!r}, which accepts: {accepted}. "
                    f"{remedy}, or pick a level the model lists. See ADR "
                    "0076."
                )
        return self


#: The nine agents that carry an effort override, paired with the
#: `<agent>_model` field whose routing decides which model that effort
#: has to be valid for. A module constant rather than a class attribute
#: because pydantic would read an annotated class attribute as a field.
EFFORT_AGENTS: Final[tuple[str, ...]] = (
    "planner",
    "reader",
    "synthesizer",
    "critic",
    "verifier",
    "supervisor",
    "query_refiner",
    "tutor",
    "assessment",
)


def _routed_model_ids(config: Settings) -> set[str]:
    """Every model id `config` can route a call to.

    The derivation `src.observability.costs.resolved_model_ids` makes
    for billing — the base model plus every non-empty `<agent>_model`
    override — and deliberately a second copy of four lines rather than
    an import: `src.observability` imports this module, so importing it
    back here to validate a field would close a cycle at settings-load
    time. `tests/test_config.py` asserts the two agree.
    """
    base = config.anthropic_model
    ids = {base}
    for name in type(config).model_fields:
        if name == "anthropic_model" or not name.endswith("_model"):
            continue
        value = getattr(config, name)
        ids.add(value or base)
    return ids


settings = Settings()
"""Module-level singleton. Import this everywhere instead of instantiating."""
