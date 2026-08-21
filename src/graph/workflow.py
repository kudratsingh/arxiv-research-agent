"""LangGraph workflow: wires agents together with conditional routing.

Two workflow shapes are supported, chosen by `settings.enable_supervisor`:

- **Fixed pipeline (default)**: planner -> search -> reader ->
  synthesizer -> critic, with one conditional route from the critic
  back to planner / search / synthesizer or to END.
- **Supervisor loop**: START -> supervisor -> chosen node -> supervisor
  -> ... -> stop. The supervisor picks the next action every turn
  from a strict enum; unknown / bad actions fall back to the
  fixed-pipeline order. See ADR 0014.

Two production knobs configured here regardless of shape:

- **Checkpointing** — selected by `settings.checkpoint_backend`,
  with the sync/async surface selected by the caller. The CLI and
  eval runner drive the graph with the sync `invoke` and get
  `SqliteSaver` / `PostgresSaver`; the API runner drives it with
  `astream` and must pass `async_checkpointer=True` for
  `AsyncSqliteSaver` / `AsyncPostgresSaver` — the sync savers raise
  `NotImplementedError` from their async methods, which killed
  every API job before its first node ran. See ADR 0013 (original
  SQLite choice), ADR 0034 (Postgres migration) and ADR 0040
  (async surface).
- **Tracing** via `traced_node` (ADR 0012 follow-up). When
  `settings.enable_tracing` is on, every agent execution becomes an
  OpenTelemetry span with `run_id` / query / iteration attributes.
- **Node execution** — agents are synchronous functions. The sync
  build registers them as-is. The async build registers an async
  wrapper that dispatches each node onto a caller-supplied
  `ThreadPoolExecutor` and registers the running thread on the job's
  cancel token, because LangGraph's own coercion hard-codes the
  loop's *default* pool and leaves no way to cancel or even observe
  the thread. See ADR 0047.

The compiled workflow is expensive to construct (opens the
checkpointer's connection). Callers should build ONCE at app
startup and reuse across requests — see `src/api/app.py::lifespan`.
Per-request compilation would leak a checkpointer connection per
job (audit finding, closed by ADR 0034).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Hashable
from concurrent.futures import Executor
from contextlib import AsyncExitStack, ExitStack
from contextvars import copy_context
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from src.agents.critic import critic_agent
from src.agents.planner import planner_agent
from src.agents.query_refiner import query_refiner_agent
from src.agents.reader import reader_agent
from src.agents.search import search_agent
from src.agents.supervisor import route_after_supervisor, supervisor_agent
from src.agents.synthesizer import synthesizer_agent
from src.agents.verifier import verifier_agent
from src.cancellation import CancelToken, current_cancel_token
from src.config import settings
from src.graph.state import ResearchState
from src.observability import get_logger, traced_node

log = get_logger(__name__)

NodeFn = Callable[[ResearchState], dict[str, Any]]
"""Shape every agent node function shares: state in, partial state out."""

NodeWrapper = Callable[[str, NodeFn], Any]
"""Turns `(node_name, agent_fn)` into whatever gets registered on the graph.

Two implementations: `_traced_wrapper` for the sync build (CLI + eval
drive `invoke`, so the node stays a plain callable) and
`_executor_wrapper` for the async build the API runner drives — see
ADR 0047.
"""


def route_after_critique(state: ResearchState) -> str:
    """Conditional edge: route based on critic's revision decision.

    Returns the node name to route to, or END to finish.
    """
    if not state.get("revision_needed", False):
        return END

    target = state.get("revision_target", "")
    if target in ("planner", "search", "synthesizer"):
        return target

    # The critic asked for a revision but named a target this router
    # cannot dispatch. Finishing is the safe fallback (the draft
    # ships with its failing quality_score attached), but it must be
    # visible — a silent END here reads as an approved report
    # (audit P3; validating the target at the critic is the fuller
    # fix, tracked in ADR 0040's follow-ups).
    log.warning(
        "revision_target_undispatchable",
        extra={"revision_target": target, "run_id": state.get("run_id")},
    )
    return END


def _open_checkpointer(exit_stack: ExitStack) -> Any | None:
    """Open the configured checkpointer, register teardown on the stack.

    Returns `None` when checkpointing is disabled so
    `workflow.compile()` gets a plain compile call.

    Backend selection follows `settings.checkpoint_backend`:

    - `sqlite` — `SqliteSaver` at `settings.checkpoint_db_path`. Same
      as the original ADR-0013 shape. Only safe under a single
      writer (one uvicorn worker).
    - `postgres` — `PostgresSaver` at `settings.postgres_url`. Runs
      the shipped `.setup()` DDL once per process; safe under
      multiple concurrent writers, required for the ADR-0034
      cross-worker HITL story.
    """
    if not settings.enable_checkpointing:
        return None

    backend = settings.checkpoint_backend
    if backend == "postgres":
        return _open_postgres_checkpointer(exit_stack)
    if backend == "sqlite":
        return _open_sqlite_checkpointer(exit_stack)
    raise ValueError(
        f"Unknown checkpoint_backend={backend!r}; expected 'sqlite' or 'postgres'."
    )


def _open_sqlite_checkpointer(exit_stack: ExitStack) -> Any:
    """SqliteSaver at `settings.checkpoint_db_path`."""
    # Import kept local so the checkpoint-sqlite dep is optional at
    # import time — if a user removes it, only compilation fails.
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cm = SqliteSaver.from_conn_string(str(db_path))
    return exit_stack.enter_context(cm)


def _open_postgres_checkpointer(exit_stack: ExitStack) -> Any:
    """PostgresSaver at `settings.postgres_url`, schema initialized.

    Fails fast with a helpful error when the URL is empty — that's
    almost always a misconfiguration (the compose file sets it; a
    manual deploy must too).
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    url = settings.postgres_url
    if not url:
        raise RuntimeError(
            "checkpoint_backend=postgres requires POSTGRES_URL to be set; "
            "the compose stack wires this automatically."
        )
    cm = PostgresSaver.from_conn_string(url)
    saver = exit_stack.enter_context(cm)
    # `.setup()` is idempotent — LangGraph ships CREATE TABLE IF NOT
    # EXISTS DDL for its own checkpoint tables. Safe under multi-
    # worker cold start.
    saver.setup()
    return saver


async def _aopen_checkpointer(exit_stack: AsyncExitStack) -> Any | None:
    """Async twin of `_open_checkpointer` for the API runner (ADR 0040).

    The runner drives the graph with `astream` / `aget_state` /
    `aupdate_state`, whose Pregel loop calls the checkpointer's async
    surface unconditionally. The sync savers inherit that surface from
    `BaseCheckpointSaver`, which raises `NotImplementedError` — so the
    async path gets real async savers instead.
    """
    if not settings.enable_checkpointing:
        return None

    backend = settings.checkpoint_backend
    if backend == "postgres":
        return await _aopen_postgres_checkpointer(exit_stack)
    if backend == "sqlite":
        return await _aopen_sqlite_checkpointer(exit_stack)
    raise ValueError(
        f"Unknown checkpoint_backend={backend!r}; expected 'sqlite' or 'postgres'."
    )


async def _aopen_sqlite_checkpointer(exit_stack: AsyncExitStack) -> Any:
    """AsyncSqliteSaver (aiosqlite) at `settings.checkpoint_db_path`."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    return await exit_stack.enter_async_context(cm)


async def _aopen_postgres_checkpointer(exit_stack: AsyncExitStack) -> Any:
    """AsyncPostgresSaver on a reconnecting `AsyncConnectionPool`.

    Deliberately a pool rather than `from_conn_string` (which the sync
    path still uses): a single `psycopg` connection never reconnects,
    so one Postgres restart would wedge every worker's checkpoint path
    for the rest of the process's life — the whole workflow is
    compiled once at startup (ADR 0034) and shares this saver. The
    pool checks out a connection per checkpoint operation, health-
    checks it (`check_connection`), and replaces dead ones, so a
    database blip costs one failed job instead of a rolling restart.

    Connection kwargs mirror what `AsyncPostgresSaver.from_conn_string`
    would set itself: autocommit (setup's DDL and the saver's writes
    manage their own transactions), `dict_row` (the saver reads rows
    by column name), `prepare_threshold=0` (PgBouncer-safe).
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    url = settings.postgres_url
    if not url:
        raise RuntimeError(
            "checkpoint_backend=postgres requires POSTGRES_URL to be set; "
            "the compose stack wires this automatically."
        )
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        url,
        min_size=1,
        # Each running job holds at most one checkpoint operation at a
        # time, so the concurrency ceiling is the natural pool bound.
        max_size=max(4, settings.api_max_concurrent_jobs),
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
            "connect_timeout": 10,
        },
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open()
    exit_stack.push_async_callback(pool.close)
    saver = AsyncPostgresSaver(pool)
    # Same idempotent DDL as the sync path.
    await saver.setup()
    return saver


def _traced_wrapper(name: str, fn: NodeFn) -> Any:
    """Sync-path node: tracing only, still a plain synchronous callable.

    LangGraph's `invoke` (CLI, eval runner) needs a sync node; the
    async-only wrapper below would make `RunnableCallable` raise for
    lack of a synchronous surface.
    """
    return traced_node(name, fn)


def _run_node_body(
    name: str,
    fn: NodeFn,
    state: ResearchState,
    token: CancelToken | None,
) -> dict[str, Any]:
    """Execute one node inside the worker thread (ADR 0047).

    Registers the thread on the job's cancel token for the whole call so
    the runner's drain can tell "the coroutine was cancelled" apart from
    "the thread has actually returned" — the distinction the timeout
    path used to get wrong, releasing the semaphore permit while the
    node kept burning CPU and LLM dollars.

    Args:
        name: Graph node name, used in the drain's log line.
        fn: The (already traced) agent callable.
        state: Graph state to hand the agent.
        token: The job's cancel token, or `None` for programmatic
            callers that run without one.

    Returns:
        The agent's partial state update.

    Raises:
        JobCancelledError: When the token was set before the thread got
            scheduled — the queued-behind-a-slow-pool case, where
            running the node would spend against an already-dead job.
    """
    if token is None:
        return fn(state)
    token.raise_if_cancelled()
    handle = token.enter_node(name)
    try:
        return fn(state)
    finally:
        token.exit_node(handle)


def _executor_wrapper(executor: Executor | None) -> NodeWrapper:
    """Build the async-path node factory bound to `executor` (ADR 0047).

    LangGraph coerces a *sync* node callable with
    `partial(run_in_executor, None, fn)` — a hard-coded `None` that
    routes every node onto the event loop's default thread pool. That
    pool is sized independently of `api_max_concurrent_jobs` and shared
    with every other `to_thread` caller in the process, so the job
    semaphore bounded coroutines rather than threads. There is no
    supported hook to override it (see ADR 0047's alternatives), so the
    node is registered as an *async* callable that does the executor
    dispatch itself.

    Args:
        executor: Pool the nodes run on. `None` falls back to the
            loop's default executor, preserving the pre-ADR-0047
            behaviour for callers that build an async graph without one.

    Returns:
        A `NodeWrapper` producing async node callables.
    """

    def wrap(name: str, fn: NodeFn) -> Any:
        traced = traced_node(name, fn)

        async def node(state: ResearchState) -> dict[str, Any]:
            token = current_cancel_token()
            if token is not None:
                # Cheap pre-check on the loop side: never occupy a pool
                # slot for a job that is already cancelled.
                token.raise_if_cancelled()
            loop = asyncio.get_running_loop()
            # Explicit context copy: `run_in_executor` only propagates
            # contextvars on its default-executor branch, and run_id /
            # cost accumulator / cancel token all have to reach the
            # node thread.
            ctx = copy_context()
            return await loop.run_in_executor(
                executor, ctx.run, _run_node_body, name, traced, state, token
            )

        node.__name__ = name
        return node

    return wrap


def _build_fixed_pipeline(
    workflow: StateGraph[ResearchState, Any, Any, Any], wrap: NodeWrapper
) -> None:
    """Wire the classic planner -> search -> reader -> synthesizer -> critic path."""
    workflow.add_node("planner", wrap("planner", planner_agent))
    workflow.add_node("search", wrap("search", search_agent))
    workflow.add_node("reader", wrap("reader", reader_agent))
    workflow.add_node("synthesizer", wrap("synthesizer", synthesizer_agent))
    workflow.add_node("critic", wrap("critic", critic_agent))

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "search")
    workflow.add_edge("search", "reader")
    workflow.add_edge("reader", "synthesizer")
    workflow.add_edge("synthesizer", "critic")

    workflow.add_conditional_edges(
        "critic",
        route_after_critique,
        {
            "planner": "planner",
            "search": "search",
            "synthesizer": "synthesizer",
            END: END,
        },
    )


def _build_supervisor_loop(
    workflow: StateGraph[ResearchState, Any, Any, Any], wrap: NodeWrapper
) -> None:
    """Wire the supervisor -> action -> supervisor loop.

    Every agent node hands control back to the supervisor when it
    finishes; the supervisor's conditional edge picks the next node
    or terminates.

    Optional nodes are only added when their flags are on:
      - `verifier` — `settings.enable_verifier`
      - `query_refiner` — `settings.enable_query_refiner`

    When a flag is off, the supervisor's action enum excludes the
    corresponding action (see `_available_actions` in the supervisor
    module), so those branches of the conditional edge are
    unreachable.
    """
    workflow.add_node("supervisor", wrap("supervisor", supervisor_agent))
    workflow.add_node("planner", wrap("planner", planner_agent))
    workflow.add_node("search", wrap("search", search_agent))
    workflow.add_node("reader", wrap("reader", reader_agent))
    workflow.add_node("synthesizer", wrap("synthesizer", synthesizer_agent))
    workflow.add_node("critic", wrap("critic", critic_agent))

    action_nodes = ["planner", "search", "reader", "synthesizer", "critic"]
    route_map: dict[Hashable, str] = {n: n for n in action_nodes}

    if settings.enable_verifier:
        workflow.add_node("verifier", wrap("verifier", verifier_agent))
        action_nodes.append("verifier")
        route_map["verifier"] = "verifier"

    if settings.enable_query_refiner:
        workflow.add_node(
            "query_refiner",
            wrap("query_refiner", query_refiner_agent),
        )
        action_nodes.append("query_refiner")
        route_map["query_refiner"] = "query_refiner"

    workflow.set_entry_point("supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {**route_map, END: END},
    )

    for node in action_nodes:
        workflow.add_edge(node, "supervisor")


def _build_graph_shape(wrap: NodeWrapper) -> StateGraph[ResearchState, Any, Any, Any]:
    """Wire the node graph — same edges for the sync and async builds.

    Args:
        wrap: How each agent callable is turned into a graph node. The
            edges are identical either way; only the node's calling
            convention differs (sync callable vs. ADR-0047 async
            executor dispatch).
    """
    workflow = StateGraph(ResearchState)
    if settings.enable_supervisor:
        _build_supervisor_loop(workflow, wrap)
    else:
        _build_fixed_pipeline(workflow, wrap)
    return workflow


def _compile(
    workflow: StateGraph[ResearchState, Any, Any, Any],
    checkpointer: Any | None,
    enable_hitl: bool | None,
) -> Any:
    """Compile with the HITL interrupt when configuration allows it.

    HITL breakpoint (ADR 0030): interrupt after the planner so a
    human can review + edit sub_questions / search_queries before
    search runs. Interrupts require a checkpointer — LangGraph
    can't resume without persistence. Bypass with `hitl_bypass=True`
    on the API caller side (see runner.py).
    """
    hitl_effective = (
        settings.enable_hitl if enable_hitl is None else enable_hitl
    )
    compile_kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
        if hitl_effective:
            compile_kwargs["interrupt_after"] = ["planner"]
    return workflow.compile(**compile_kwargs)


async def _abuild_workflow(
    enable_hitl: bool | None, node_executor: Executor | None
) -> Any:
    """Async-mode build: async savers, `AsyncExitStack` teardown."""
    exit_stack = AsyncExitStack()
    try:
        checkpointer = await _aopen_checkpointer(exit_stack)
    except BaseException:
        await exit_stack.aclose()
        raise
    compiled = _compile(
        _build_graph_shape(_executor_wrapper(node_executor)),
        checkpointer,
        enable_hitl,
    )
    # The lifespan awaits this stack's `aclose()` at shutdown — see
    # `create_app` in src/api/app.py.
    compiled._checkpointer_aexit_stack = exit_stack
    return compiled


def build_workflow(
    *,
    enable_hitl: bool | None = None,
    async_checkpointer: bool = False,
    node_executor: Executor | None = None,
) -> Any:
    """Construct and compile the research agent workflow graph.

    Shape depends on `settings.enable_supervisor`:
    - Off (default) — fixed pipeline with a single conditional edge on
      the critic.
    - On — supervisor loop; every agent hands control back to the
      supervisor, which picks the next action or stops.

    When `settings.enable_checkpointing` is on, the compiled graph
    persists state after each node so a run can be resumed by
    invoking with `config={"configurable": {"thread_id": <run_id>}}`.

    When `settings.enable_tracing` is on, every agent execution is
    wrapped in an OpenTelemetry span.

    Args:
        enable_hitl: Override for the HITL breakpoint (ADR 0030).
            `None` (default) reads `settings.enable_hitl`. Pass `False`
            from the eval runner + other programmatic callers that
            can't sit through a human review — matches the per-query
            `hitl_bypass` flag on `POST /research`.
        async_checkpointer: When True, return an *awaitable* that
            resolves to the compiled graph, built on the async savers
            (`AsyncSqliteSaver` / `AsyncPostgresSaver` on a
            reconnecting pool) the `astream`-driven API runner
            requires — the sync savers raise `NotImplementedError`
            from every async method, so no sync-saver graph can serve
            an API job (ADR 0040). The default False keeps the sync
            savers and a plain return value for the CLI and the eval
            runner, which drive the graph with the sync `invoke`.
        node_executor: Thread pool the graph's synchronous nodes run
            on (ADR 0047). Async mode only — the pool is what makes
            `api_max_concurrent_jobs` bound real threads instead of
            coroutines, and what gives the runner's timeout drain and
            the lifespan's shutdown join something to wait on. `None`
            falls back to the event loop's default executor.

    Returns:
        The compiled graph (sync mode), or a coroutine resolving to it
        (async mode — the `create_app` lifespan awaits it). Teardown
        handles are attached as `_checkpointer_exit_stack` /
        `_checkpointer_aexit_stack` respectively.

    Raises:
        ValueError: When `node_executor` is passed without
            `async_checkpointer` — the sync `invoke` path calls nodes
            inline on the caller's thread, so an executor there would
            be silently ignored.
    """
    if async_checkpointer:
        return _abuild_workflow(enable_hitl, node_executor)

    if node_executor is not None:
        raise ValueError(
            "node_executor applies to the async build only; the sync "
            "path calls nodes inline. Pass async_checkpointer=True "
            "(see ADR 0047)."
        )

    # ExitStack keeps the SqliteSaver context alive for the compiled
    # graph's lifetime. We attach it to the compiled object so callers
    # don't have to think about teardown.
    exit_stack = ExitStack()
    checkpointer = _open_checkpointer(exit_stack)
    compiled = _compile(
        _build_graph_shape(_traced_wrapper), checkpointer, enable_hitl
    )

    # Attach so a caller who cares can `close()`; ExitStack cleanup
    # otherwise runs at interpreter shutdown.
    compiled._checkpointer_exit_stack = exit_stack
    return compiled
