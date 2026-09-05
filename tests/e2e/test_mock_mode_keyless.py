"""The keyless path: a briefing with no credential and no canned agent.

CAP-07, ADR 0080. Every other module in this directory proves what the
graph does when the *harness* supplies the model's words. This one
proves what the product does when nobody supplies them at all, which is
the configuration `docker compose up` lands a first-time reader in and
the one the assurance lane measured as `failed`,
`error_type=upstream_model`, `llm_calls=0` after four seconds.

**No canned agents, deliberately.** `research_llm_surface` is not used
here — it exists to can the four agents *and*, since ADR 0080, to turn
their own mock branch off so its patches are reachable. Using it would
make this module a test of the fixture. The one thing patched below is
`rank_papers_by_relevance`, which is a local MiniLM checkpoint rather
than a model call: pinning it keeps the tier independent of whether the
checkpoint happens to be cached on the host, exactly as the e2e
conftest and `tests/test_api_smoke_e2e.py` already pin it.

**Two proofs of "no model", because they fail differently.** The
autouse `zero_spend_ledger` proves nothing was *billed*; the
`no_client_constructed` fixture proves nothing was even *built*. A
zero-cost ledger is consistent with a client that was constructed and
then failed, which is precisely the shape of the outage this work order
exists to remove — so the second assertion is the load-bearing one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from httpx import AsyncClient
from pydantic import SecretStr

from src.agents.mock_mode import MOCK_BANNER, MOCK_QUALITY_SCORE
from src.eval.groundedness import measure_groundedness
from src.graph.state import ResearchState, initial_research_state
from src.graph.workflow import build_workflow
from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: The fixed pipeline's shape, spelled out rather than read off the
#: graph, for the reason `test_research_workflow.py` gives: a
#: trajectory assertion that asks the graph what to expect agrees with
#: any rewiring, including a wrong one.
FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")

#: Loopback only; the guard in `tests/conftest.py` refuses anything else.
SERVER_HOST = "127.0.0.1"

TERMINAL_TIMEOUT_SEC = 30.0


@pytest.fixture
def no_client_constructed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Blank the key `src/llm.py` reads, and record any client build.

    Two things, because "keyless" has to be true of the module that
    reads the key rather than only of the ones this tier's
    `install_settings` reaches: `src.llm` is not in `SETTINGS_CONSUMERS`
    (nothing in the tier had ever needed it to be), so its own binding
    is rebound here to a blank-key copy. That is the deployed state —
    an operator who ran `docker compose up` and never filled the
    variable in.

    The refusal is stricter than the harness guard it displaces:
    `tests/conftest.py` raises when a real client would be built, and
    this additionally keeps the evidence, so a test can assert on
    *absence* rather than on "no exception happened to escape". That
    distinction is load-bearing here — the five agents' fallbacks are
    `except Exception` sites, so an exception that fired and was
    swallowed would leave a green test and a report no model wrote.
    """
    import src.llm as llm_module

    monkeypatch.setattr(
        llm_module,
        "settings",
        llm_module.settings.model_copy(update={"anthropic_api_key": SecretStr("")}),
    )

    reached: list[str] = []

    def _refuse() -> Any:
        reached.append("_get_client")
        raise AssertionError(
            "the keyless path constructed a provider client; mock mode is "
            "supposed to return before src/llm.py is reached"
        )

    monkeypatch.setattr(llm_module, "_get_client", _refuse)
    yield reached
    assert reached == [], f"provider client constructed: {reached}"


@pytest.fixture
def offline_ranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity paper ranking — the only stub in this module.

    Not a model call: `rank_papers_by_relevance` loads a local MiniLM
    checkpoint and computes cosine similarity. The five fixture papers
    already fit under `max_papers`, so the identity slice is the same
    answer the real ranker gives, without making the tier depend on a
    downloaded checkpoint.
    """
    monkeypatch.setattr(
        "src.agents.search.rank_papers_by_relevance",
        lambda query, papers, top_k: list(papers)[:top_k],
    )


def _drive(app: Any, state: ResearchState) -> tuple[list[str], dict[str, Any]]:
    """Run the graph to completion, recording the node sequence."""
    visited: list[str] = []
    final: dict[str, Any] = {}
    for mode, payload in app.stream(state, stream_mode=["updates", "values"]):
        if mode == "values":
            final = dict(payload)
            continue
        visited.extend(node for node in payload if node != "__interrupt__")
    return visited, final


class TestTheKeylessGraph:
    def test_a_query_reaches_a_labelled_briefing_with_no_model_and_no_key(
        self,
        install_settings: Callable[..., Any],
        offline_ranker: None,
        no_client_constructed: list[str],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The whole fixed pipeline, keyless, to a briefing that says so.

        `install_settings` supplies `use_mock_data=True` from
        `BASE_OVERRIDES`; the blank key is set here so the state under
        test is the deployed one — a compose stack whose operator never
        filled in `ANTHROPIC_API_KEY`.
        """
        install_settings(
            enable_checkpointing=False,
            enable_supervisor=False,
            anthropic_api_key=SecretStr(""),
        )

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app,
                initial_research_state("why do LLMs hallucinate?", "e2e-mock-1"),
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == list(FIXED_PIPELINE)

        # The label, first and exact. A mock report that read as a real
        # one would be worse than no report at all.
        assert final["draft_report"].splitlines()[0] == MOCK_BANNER

        # Evidence the five nodes were connected rather than merely run:
        # the plan reached search, the corpus reached the reader, the
        # analyses reached the synthesizer, the critic's verdict landed.
        assert final["sub_questions"] and final["search_queries"]
        assert len(final["papers"]) == 5, "mock search serves five fixture papers"
        assert len(final["paper_analyses"]) == len(final["papers"])
        assert final["iteration"] == 1
        assert final["revision_needed"] is False
        assert final["quality_score"] == pytest.approx(MOCK_QUALITY_SCORE)

        # Citations that resolve, not just citations. Both surfaces
        # `src/eval/groundedness.py` checks carry every identifier, so a
        # mock briefing is scored by the same oracle a real one is.
        assert len(final["citations"]) == len(final["papers"])
        result = measure_groundedness(
            final["draft_report"], final["papers"], final["citations"]
        )
        resolution = result["citation_resolution_rate"]
        assert resolution["denominator"] == 2 * len(final["papers"])
        assert resolution["value"] == 1.0
        assert result["unsupported_claim_count"]["numerator"] == 0

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    def test_the_evidence_path_quotes_the_abstract_it_claims_to(
        self,
        install_settings: Callable[..., Any],
        offline_ranker: None,
        no_client_constructed: list[str],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Evidence claims are verbatim spans of the paper's abstract.

        `source_text` is what the verifier and ADR 0074's check judge
        against, so a claim whose source cannot be found in the paper is
        the exact defect the evidence store exists to prevent. The live
        reader guarantees it by refusing to build a claim without a
        ranked chunk; mock mode guarantees it by making the claim and
        its source the same slice of the abstract.
        """
        install_settings(
            enable_checkpointing=False,
            enable_supervisor=False,
            enable_evidence_store=True,
            anthropic_api_key=SecretStr(""),
        )

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("grounded run", "e2e-mock-evidence")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == list(FIXED_PIPELINE)
        assert final["draft_report"].splitlines()[0] == MOCK_BANNER

        abstracts = {paper["id"]: paper["abstract"] for paper in final["papers"]}
        claims = final["evidence"]
        assert claims, "the evidence path must produce claims"
        assert {claim["paper_id"] for claim in claims} == set(abstracts)
        for claim in claims:
            assert claim["source_text"] in abstracts[claim["paper_id"]], (
                f"claim source is not verbatim in the abstract it names: "
                f"{claim['source_text']!r}"
            )
            assert claim["claim"] == claim["source_text"]
            assert claim["supports_question"] in final["sub_questions"]

        # The evidence path changes what the briefing quotes, never what
        # it cites — so the two paths score identically and a run cannot
        # be told apart by its groundedness numbers.
        result = measure_groundedness(
            final["draft_report"],
            final["papers"],
            final["citations"],
            evidence=claims,
        )
        assert result["citation_resolution_rate"]["value"] == 1.0
        assert result["citation_resolution_rate"]["denominator"] == 10
        # Honestly undecided rather than manufactured: a mock briefing
        # quotes nothing, so the quote half of ADR 0074 has no
        # denominator and says which reason.
        assert result["quote_verbatim_rate"]["value"] is None
        assert result["quote_verbatim_rate"]["reason"] == "no_quotes"

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0


# ---------------------------------------------------------------------------
# The same claim, over HTTP, on the shipped wiring
# ---------------------------------------------------------------------------


@pytest.fixture
async def keyless_server(
    install_settings: Callable[..., Any],
    offline_ranker: None,
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    """`create_app`'s own wiring on a loopback port, with a blank key.

    No injected factory, no injected store and no canned agent: the
    configuration under test is the one an operator gets from
    `docker compose up` without an `ANTHROPIC_API_KEY`, which is the
    only configuration whose failure this work order was opened for.
    Uvicorn rather than `ASGITransport` for the reason
    `test_http_surface.py` gives — this is the transport a browser uses.
    """
    install_settings(
        enable_checkpointing=True,
        checkpoint_backend="sqlite",
        checkpoint_db_path=str(tmp_path / "e2e-mock-http.sqlite"),
        enable_hitl=True,  # shipped default; the request opts out per job
        enable_api_auth=False,
        anthropic_api_key=SecretStr(""),
    )

    from src.api.app import create_app

    config = uvicorn.Config(
        create_app(),
        host=SERVER_HOST,
        port=0,
        log_config=None,
        access_log=False,
        lifespan="on",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve(), name="e2e-mock-uvicorn")
    try:
        deadline = asyncio.get_running_loop().time() + 20.0
        while not server.started:
            assert not serving.done(), "server exited during startup"
            assert asyncio.get_running_loop().time() < deadline, "server never started"
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with AsyncClient(
            base_url=f"http://{SERVER_HOST}:{port}", timeout=TERMINAL_TIMEOUT_SEC
        ) as client:
            yield client
    finally:
        server.should_exit = True
        await serving


class TestTheKeylessHttpSurface:
    async def test_a_job_submitted_without_a_key_succeeds_and_exports(
        self,
        keyless_server: AsyncClient,
        no_client_constructed: list[str],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """202, then `succeeded` — not `failed / upstream_model`.

        This is the acceptance criterion for CAP-07 stated as an
        assertion. The measured behaviour it replaces is a 202 followed
        four seconds later by a `failed` job with
        `error_type=upstream_model` and `llm_calls=0`, so both the
        status and the *absence* of an error type are checked: a job
        that succeeded with an error type recorded would be a different
        bug wearing this one's clothes.
        """
        client = keyless_server

        submit = await client.post(
            "/research", json={"query": "why do LLMs hallucinate?", "hitl_bypass": True}
        )
        assert submit.status_code == 202, submit.text
        accepted = submit.json()
        job_id = accepted["job_id"]

        deadline = asyncio.get_running_loop().time() + TERMINAL_TIMEOUT_SEC
        body: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            body = (await client.get(accepted["status_url"])).json()
            if body["status"] in ("succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(0.02)

        assert body.get("status") == "succeeded", (
            f"keyless job ended {body.get('status')!r}: "
            f"{body.get('error_type')}: {body.get('error')}"
        )
        assert body["error"] is None and body["error_type"] is None
        assert body["result"].splitlines()[0] == MOCK_BANNER
        assert body["iterations"] == 1
        assert body["quality_score"] == pytest.approx(MOCK_QUALITY_SCORE)

        # The job's own ledger — the accumulator this test holds is
        # bound to a different context and cannot see the run.
        assert usd(body["cost_usd"]) == "$0.0000"
        assert body["llm_calls"] == 0

        export = await client.get(f"/research/{job_id}/export", params={"format": "md"})
        assert export.status_code == 200
        document = export.text
        # The label survives into the file a user downloads, which is
        # the artefact most likely to outlive the run that made it.
        assert MOCK_BANNER in document
        assert "| Cost | $0.0000 |" in document

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_the_stream_reports_the_same_free_terminal_frame(
        self,
        keyless_server: AsyncClient,
        no_client_constructed: list[str],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """A client watching the stream is told the run was free.

        The terminal frame is where a browser learns the outcome without
        a follow-up `GET`, and it is built by different code from the
        status route's body. Asserting the cost on both is what keeps
        the keyless claim true on the surface a user actually watches.
        """
        client = keyless_server
        from src.api.streaming import TERMINAL_EVENT_NAMES

        submit = await client.post(
            "/research", json={"query": "keyless stream", "hitl_bypass": True}
        )
        assert submit.status_code == 202
        accepted = submit.json()

        frames: list[tuple[str, dict[str, Any]]] = []
        buffer = ""
        async with client.stream("GET", accepted["stream_url"]) as response:
            assert response.status_code == 200
            async for text in response.aiter_text():
                buffer += text
                complete, separator, buffer = buffer.rpartition("\n\n")
                if not separator:
                    continue
                for block in (complete + "\n\n").split("\n\n"):
                    name = ""
                    payload = ""
                    for line in block.splitlines():
                        if line.startswith("event: "):
                            name = line[len("event: ") :]
                        elif line.startswith("data: "):
                            payload = line[len("data: ") :]
                    if name:
                        frames.append((name, json.loads(payload) if payload else {}))
                if any(name in TERMINAL_EVENT_NAMES for name, _ in frames):
                    break

        names = [name for name, _ in frames]
        assert names[-1] == "job_completed"
        # Every node frame that *was* seen names a pipeline node and
        # arrives in pipeline order. Not asserted as the full list: with
        # no canned agent to hold at a gate the run can finish before
        # the client attaches, and the route then legally replays one
        # terminal frame (`test_http_surface.py` owns that case).
        node_frames = [data["node"] for name, data in frames if name == "node_completed"]
        assert node_frames == [n for n in FIXED_PIPELINE if n in node_frames]

        terminal = next(data for name, data in frames if name == "job_completed")
        assert terminal["status"] == "succeeded"
        assert usd(terminal["cost_usd"]) == "$0.0000"
        assert terminal["llm_calls"] == 0

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0


