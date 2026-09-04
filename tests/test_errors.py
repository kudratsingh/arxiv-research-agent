"""The taxonomy's own invariants (ADR 0064).

`src/errors.py` is a contract, not a convenience: `code` is simultaneously
an API field, a job record field and a metric attribute, so the properties
this file pins are the ones whose violation is silent everywhere else — a
duplicate code that makes two failures indistinguishable, a code outside
the closed set that forks a metric series, a family whose HTTP status
drifts from what `03-ARCHITECTURE.md` §2.1 assigned it.

The boundary-typing test at the bottom is the structural one. It reads the
route modules rather than exercising them, because the property being
proven — "no `raise` reachable from a handler produces an untyped error" —
is about paths no test happens to walk, which is exactly the set an
integration test cannot cover.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.errors import (
    ERROR_CODES,
    JOB_ERROR_TYPES,
    AppError,
    BudgetExceededError,
    CancellationError,
    ConflictError,
    ForbiddenError,
    GatewayTimeoutError,
    InvalidRequestError,
    JobNotFound,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    UpstreamError,
    error_class_for_code,
    error_class_for_status,
    error_envelope,
    registered_error_classes,
    state_conflict_message,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]

#: The modules whose `raise` statements can reach an HTTP response, a job
#: record, or a metric attribute — the "boundary" in boundary typing.
#: `learn.py` is deliberately absent: WO-A01 does not own it, and its
#: `HTTPException`s are covered by the `HTTPException` handler instead.
#: See `test_no_boundary_module_raises_an_untyped_http_error`.
BOUNDARY_MODULES = (
    ROOT / "src" / "api" / "routes.py",
    ROOT / "src" / "api" / "auth.py",
    ROOT / "src" / "api" / "sessions.py",
)


def _subclasses(cls: type[AppError]) -> set[type[AppError]]:
    """Every `AppError` subclass reachable from `cls`, transitively."""
    found: set[type[AppError]] = set()
    for child in cls.__subclasses__():
        found.add(child)
        found |= _subclasses(child)
    return found


class TestTheClosedSet:
    def test_every_subclass_declares_a_code_that_is_in_the_closed_set(self) -> None:
        # Import the modules that define subclasses outside `errors.py`,
        # so re-parented classes are counted rather than merely assumed.
        import src.api.runner  # noqa: F401
        import src.content.schema  # noqa: F401
        import src.learning.profile_store  # noqa: F401
        import src.learning.progress_store  # noqa: F401

        for cls in _subclasses(AppError) | {AppError}:
            assert cls.code in ERROR_CODES, f"{cls.__qualname__} -> {cls.code!r}"

    def test_the_closed_set_holds_no_code_no_class_owns(self) -> None:
        """The other direction, which is what stops the set becoming folklore.

        A code left behind by a deleted class would still look like a
        supported value to anyone reading `ERROR_CODES` — and to the
        frontend copy dictionary, which derives its keys from it.
        """
        assert set(registered_error_classes()) == set(ERROR_CODES)

    def test_two_classes_cannot_share_a_code(self) -> None:
        """The collision guard fires at class-definition time, not at use.

        Two classes under one code make every downstream consumer —
        client branch, log filter, metric series — quietly wrong rather
        than loudly broken, so it has to be impossible to write.
        """
        with pytest.raises(ValueError, match="duplicate AppError code 'job_not_found'"):

            class _Duplicate(NotFoundError):
                code = "job_not_found"

    def test_a_specialization_that_inherits_its_parents_code_is_allowed(self) -> None:
        """Inheriting a code is not a collision — it is a narrowing.

        Only a class that writes `code` in its own body enters the
        contract; `src/api/runner.py`'s `HitlTimeoutError` relies on
        this to keep its name while carrying `hitl_timeout`.
        """

        class _Narrower(JobNotFound):
            pass

        assert _Narrower.code == "job_not_found"
        assert error_class_for_code("job_not_found") is JobNotFound

    def test_every_code_is_snake_case(self) -> None:
        """A code is a wire identifier; casing drift is a client break."""
        for code in ERROR_CODES:
            assert code == code.lower()
            assert code.replace("_", "").isalnum(), code
            assert not code.startswith("_") and not code.endswith("_"), code


class TestTheFamilies:
    """`03-ARCHITECTURE.md` §2.1's table, asserted rather than described.

    The families carry the HTTP status and the retryability; that is the
    whole content of a "family", so it is what gets pinned. The `code`
    strings themselves are deliberately *not* all prefixed — see the
    module docstring of `src/errors.py` for why renaming the ones
    already on the wire was rejected.
    """

    @pytest.mark.parametrize(
        ("family", "http_status", "retryable"),
        [
            (InvalidRequestError, 422, False),
            (NotFoundError, 404, False),
            (UnauthorizedError, 401, False),
            (ForbiddenError, 403, False),
            (ConflictError, 409, False),
            (RateLimitedError, 429, True),
            (BudgetExceededError, 409, False),
            (UpstreamError, 502, True),
            (ServiceUnavailableError, 503, True),
            (GatewayTimeoutError, 504, True),
            (CancellationError, 409, False),
            (AppError, 500, False),
        ],
    )
    def test_each_family_carries_its_row_of_the_table(
        self, family: type[AppError], http_status: int, retryable: bool
    ) -> None:
        assert family.http_status == http_status
        assert family.retryable is retryable

    def test_every_status_the_boundary_can_produce_has_a_family(self) -> None:
        for http_status in (400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504):
            assert error_class_for_status(http_status).code in ERROR_CODES
        # ...and where the family owns the status outright, the round
        # trip closes. 400 is the deliberate exception: it maps onto the
        # `invalid_*` family, whose canonical status is FastAPI's 422.
        for http_status in (401, 403, 404, 409, 422, 429, 500, 502, 503, 504):
            assert error_class_for_status(http_status).http_status == http_status

    def test_an_unmapped_client_status_still_gets_a_code(self) -> None:
        """A 405 from the router is not in the table and still needs a name."""
        assert error_class_for_status(405).code == "invalid_request"
        assert error_class_for_status(418).code == "invalid_request"
        assert error_class_for_status(507).code == "internal_unexpected"


class TestTheInstance:
    def test_the_public_message_never_carries_the_log_detail(self) -> None:
        """The one property the whole module exists for.

        `log_detail` is where a psycopg DSN or an httpx URL ends up.
        Whatever else changes, it must not be reachable from `message`.
        """
        secret = "connection to server at 10.0.0.4, port 5432 failed"
        error = JobNotFound(log_detail=secret)

        assert secret not in error.message
        assert error.message == JobNotFound.public_message
        assert str(error) == secret

    def test_a_bare_error_still_says_something_in_the_log(self) -> None:
        assert str(JobNotFound()) == "job_not_found"

    def test_wire_detail_defaults_to_the_code(self) -> None:
        assert JobNotFound().wire_detail == "job_not_found"

    def test_wire_detail_can_carry_a_legacy_shape(self) -> None:
        """The two exceptions, and why they are exceptions.

        `web/lib/api/errors.ts` reads `limit_per_hour` out of the 429's
        object body and regexes `(status=...)` out of the conflict
        strings. Replacing either with a bare code would silently
        downgrade a live surface to generic copy, so the envelope is
        additive over them.
        """
        limited = RateLimitedError(wire_detail={"error": "rate_limited", "limit_per_hour": 20})
        assert limited.wire_detail == {"error": "rate_limited", "limit_per_hour": 20}
        assert limited.code == "rate_limited"

    def test_headers_ride_along(self) -> None:
        error = RateLimitedError(headers={"Retry-After": "60"})
        assert error.headers == {"Retry-After": "60"}


class TestTheEnvelope:
    def test_it_has_exactly_the_five_documented_fields(self) -> None:
        body = error_envelope(
            code="upstream_model_output",
            message="The model's output could not be used.",
            retryable=True,
            request_id="01J",
        )
        assert body == {
            "error": {
                "code": "upstream_model_output",
                "message": "The model's output could not be used.",
                "retryable": True,
                "request_id": "01J",
            },
            "detail": "upstream_model_output",
        }

    def test_detail_defaults_to_the_code_and_can_be_overridden(self) -> None:
        body = error_envelope(
            code="invalid_request",
            message="m",
            retryable=False,
            request_id=None,
            detail=[{"loc": ["body", "query"], "msg": "too long"}],
        )
        assert body["detail"] == [{"loc": ["body", "query"], "msg": "too long"}]
        assert body["error"]["code"] == "invalid_request"


class TestTheStateConflictSentence:
    def test_it_translates_the_wire_status(self) -> None:
        assert "still running" in state_conflict_message("export a report", "running")

    def test_an_unknown_status_is_never_echoed(self) -> None:
        """A status this build has not heard of must not reach the copy.

        `job.status` comes off a stored row, so a rolling deploy can
        hand this function a value the running code does not know. The
        fallback is a phrase, never the raw identifier.
        """
        message = state_conflict_message("do that", "some_future_status")
        assert "some_future_status" not in message


class TestTheJobVocabulary:
    """`JOB_ERROR_TYPES` is derived, not transcribed.

    The frontend's failure copy (`web/lib/copy/errors.ts`) requires a
    sentence for every value a *run* can carry, so a value that arrives
    without one renders "The run failed." forever. That only works if
    this set is provably the whole set — hence both directions below.
    """

    def _assigned_error_types(self, path: Path) -> set[str]:
        """Every literal `job.error_type = ...` value in one module.

        Resolves three forms: a bare string, a module-level `Final[str]`
        constant, and `SomeAppError.code`. The fourth form — the
        runner's `job.error_type = app_error.code` — is dynamic and is
        covered by `test_every_job_path_failure_class_is_in_the_set`.
        """
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        constants: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign | ast.Assign):
                targets = (
                    [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                )
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    for target in targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = value.value

        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(t, ast.Attribute) and t.attr == "error_type"
                for t in node.targets
            ):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(value.value)
            elif isinstance(value, ast.Name) and value.id in constants:
                found.add(constants[value.id])
            elif (
                isinstance(value, ast.Attribute)
                and value.attr == "code"
                and isinstance(value.value, ast.Name)
            ):
                cls = getattr(__import__("src.errors", fromlist=["x"]), value.value.id, None)
                if isinstance(cls, type) and issubclass(cls, AppError):
                    found.add(cls.code)
        return found

    def _raised_in(self, path: Path) -> set[str]:
        """Codes of the `AppError` classes a module raises directly.

        `src/llm.py` is the job path's one failure site that belongs to
        no agent module — every node reaches the provider through it —
        so its class lives in `src/errors.py` and the module-prefix
        derivation below cannot see it. Read out of the source rather
        than listed, for the same reason nothing else in this class is
        listed: a hand-maintained entry is the one that goes stale.
        """
        import src.errors as errors_module

        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            called = node.exc
            name = (
                called.func
                if isinstance(called, ast.Call)
                else called
            )
            if not isinstance(name, ast.Name):
                continue
            cls = getattr(errors_module, name.id, None)
            if isinstance(cls, type) and issubclass(cls, AppError):
                found.add(cls.code)
        return found

    def test_every_statically_assigned_error_type_is_in_the_set(self) -> None:
        assigned = self._assigned_error_types(
            ROOT / "src" / "api" / "runner.py"
        ) | self._assigned_error_types(ROOT / "src" / "api" / "redriver.py")
        # `None` assignments (a requeue clearing the field) are not
        # string literals, so they never appear here.
        assert assigned <= JOB_ERROR_TYPES, assigned - JOB_ERROR_TYPES
        # And the derivation found something, so a rename of the field
        # cannot make this pass by finding nothing.
        assert len(assigned) >= 6, assigned

    def test_every_job_path_failure_class_is_in_the_set(self) -> None:
        """The dynamic half: whatever `_as_app_error` can return.

        A failure raised anywhere under `src/agents/` or `src/tools/`
        reaches the runner's generic handler unintercepted, so its code
        becomes an `error_type`. `src/cancellation.py` and
        `src/observability/costs.py` raise classes this work order could
        not re-parent; `_as_app_error` maps both, and the mapping is
        asserted here rather than trusted.
        """
        import src.agents.reader  # noqa: F401
        import src.agents.search  # noqa: F401
        import src.agents.synthesizer  # noqa: F401
        import src.tools.arxiv_search  # noqa: F401
        from src.api.runner import _as_app_error
        from src.cancellation import JobCancelledError
        from src.observability.costs import CostBudgetExceeded

        producible = {
            cls.code
            for cls in _subclasses(AppError)
            if cls.__module__.startswith(("src.agents.", "src.tools."))
        }
        producible.add(_as_app_error(JobCancelledError("j", "cancelled")).code)
        producible.add(_as_app_error(CostBudgetExceeded(1.0, 0.5)).code)
        producible.add(_as_app_error(RuntimeError("anything")).code)
        producible |= self._raised_in(ROOT / "src" / "llm.py")

        assert producible <= JOB_ERROR_TYPES, producible - JOB_ERROR_TYPES

    def test_the_set_holds_nothing_a_run_cannot_produce(self) -> None:
        """The other direction, so the set cannot rot into folklore.

        Every member is either statically assigned by the runner or the
        redriver, or is one the dynamic half can produce.
        """
        import src.agents.reader  # noqa: F401
        import src.agents.search  # noqa: F401
        import src.agents.synthesizer  # noqa: F401
        import src.tools.arxiv_search  # noqa: F401

        static = self._assigned_error_types(
            ROOT / "src" / "api" / "runner.py"
        ) | self._assigned_error_types(ROOT / "src" / "api" / "redriver.py")
        dynamic = (
            {
                cls.code
                for cls in _subclasses(AppError)
                if cls.__module__.startswith(("src.agents.", "src.tools."))
            }
            | {"cancelled_job", "cost_budget_exceeded", "internal_unexpected"}
            # The model call is the job path's one failure site with no
            # owning agent module; `src/llm.py` raises it by name.
            | self._raised_in(ROOT / "src" / "llm.py")
        )

        assert static | dynamic == JOB_ERROR_TYPES

    def test_it_is_a_subset_of_the_closed_set(self) -> None:
        assert JOB_ERROR_TYPES < ERROR_CODES


class TestBoundaryTyping:
    """Every `raise` on the HTTP boundary produces a code from the set.

    Read structurally rather than exercised, because the claim is about
    the raises no test happens to reach.
    """

    def _raised_names(self, path: Path) -> list[tuple[str, int]]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name):
                found.append((target.id, node.lineno))
            elif isinstance(target, ast.Attribute):
                found.append((target.attr, node.lineno))
        return found

    def test_no_boundary_module_raises_an_untyped_http_error(self) -> None:
        """`HTTPException` is gone from the three modules WO-A01 owns.

        `src/api/learn.py` still raises it — that module belongs to
        another work order — which is precisely why `create_app`
        registers an `HTTPException` handler as well: the envelope has
        to hold for code this taxonomy has not reached yet.
        """
        for path in BOUNDARY_MODULES:
            names = [name for name, _ in self._raised_names(path)]
            assert "HTTPException" not in names, path

    def test_every_raise_on_the_boundary_names_a_code_in_the_closed_set(self) -> None:
        import src.api.auth as auth_module
        import src.api.routes as routes_module
        import src.api.sessions as sessions_module

        modules = {
            BOUNDARY_MODULES[0]: routes_module,
            BOUNDARY_MODULES[1]: auth_module,
            BOUNDARY_MODULES[2]: sessions_module,
        }
        checked = 0
        for path, module in modules.items():
            for name, lineno in self._raised_names(path):
                raised = getattr(module, name, None)
                # A bare `raise` of a caught exception, or a re-raise of
                # a parameter, resolves to nothing importable — those
                # are re-raises, not new failures.
                if not isinstance(raised, type) or not issubclass(raised, BaseException):
                    continue
                assert issubclass(raised, AppError), f"{path.name}:{lineno} {name}"
                assert raised.code in ERROR_CODES, f"{path.name}:{lineno} {name}"
                checked += 1
        # A refactor that empties the boundary would otherwise make this
        # test pass by proving nothing.
        assert checked >= 15, checked

    def test_the_runner_writes_no_class_name_into_a_job_field(self) -> None:
        """The `runner.py:1832` leak, asserted as absent.

        The old code was `job.error = f"{type(exc).__name__}: {exc}"`
        and `job.error_type = type(exc).__name__`. Both are gone. This
        reads the parse tree rather than the text, because the text
        still contains both strings — in the comment that records what
        was removed and why, which is worth keeping and would make a
        substring check pass for the wrong reason.
        """
        tree = ast.parse((ROOT / "src" / "api" / "runner.py").read_text(encoding="utf-8"))
        assigned: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in {
                    "error",
                    "error_type",
                }:
                    assigned.append(ast.unparse(node.value))
        assert assigned, "the runner stopped writing job.error at all"
        for value in assigned:
            assert "__name__" not in value, value
