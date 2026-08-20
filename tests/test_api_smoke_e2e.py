"""End-to-end smoke test: one job through the PRODUCTION wiring (ADR 0040).

Every prior API test injected a stub workflow, so nothing ever proved
that `create_app`'s default factory, the real compiled graph, the real
checkpointer, and the async runner agree with each other. They did
not: the shipped configuration compiled a *sync* checkpointer under an
`astream`-driven runner, and every HTTP job died on
`NotImplementedError` before its first node ran. This test exists so
that class of wiring break can never land silently again.

What is real here: `build_workflow` (fixed pipeline, HITL interrupt,
AsyncSqliteSaver at a tmp path), `create_app`'s lifespan, the runner,
the store, and the HTTP surface. What is canned: the LLM call surface
(`call_llm_json` per agent module, shape-valid responses matching what
each agent parses), PDF fetch (empty -> abstract fallback per ADR
0004), and embedding ranking (identity slice) — everything that would
otherwise touch the network, per the no-live-network test mandate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.config import Settings, settings

pytestmark = pytest.mark.integration


# ---- canned LLM responses, shaped to what each agent parses ---------

PLANNER_RESPONSE = {
    "sub_questions": ["What causes hallucination?", "How is it mitigated?"],
    "search_queries": ["LLM hallucination survey", "hallucination mitigation"],
}

# `reader._analyze_paper` requires key_findings (list), methodology /
# results_summary / limitations (str), relevance (float).
READER_RESPONSE = {
    "key_findings": ["RAG grounds generations in retrieved text."],
    "methodology": "Survey of mitigation techniques.",
    "results_summary": "Retrieval reduces factual errors.",
    "limitations": "Abstract-only analysis.",
    "relevance": 0.9,
}

SYNTHESIZER_RESPONSE = {
    "draft_report": (
        "# Hallucination in LLMs\n\n"
        "Retrieval-augmented generation grounds model output in "
        "retrieved documents [Ji, 2023].\n"
    ),
    "citations": [
        {
            "paper_id": "http://arxiv.org/abs/2311.09000",
            "title": "A Survey on Hallucination in Large Language Models",
            "authors": ["Ziwei Ji"],
            "year": 2023,
            "url": "http://arxiv.org/abs/2311.09000",
        }
    ],
}

CRITIC_RESPONSE = {
    "scores": {
        "completeness": 0.9,
        "accuracy": 0.9,
        "coherence": 0.9,
        "depth": 0.8,
        "balance": 0.9,
    },
    "average_score": 0.88,
    "critique": "Solid coverage of the question.",
    "revision_needed": False,
    "revision_target": "none",
}


def _canned(response: dict[str, Any]) -> Any:
    """A `call_llm_json` stand-in that ignores its prompt arguments."""

    def _call(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(response)

    return _call


def _patch_llm_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cannedify every network-touching seam under the real graph.

    `call_llm_json` is imported into each agent module's namespace, so
    the patch has to land per-module rather than on `src.llm`.
    """
    monkeypatch.setattr(
        "src.agents.planner.call_llm_json", _canned(PLANNER_RESPONSE)
    )
    monkeypatch.setattr(
        "src.agents.reader.call_llm_json", _canned(READER_RESPONSE)
    )
    monkeypatch.setattr(
        "src.agents.synthesizer.call_llm_json", _canned(SYNTHESIZER_RESPONSE)
    )
    monkeypatch.setattr(
        "src.agents.critic.call_llm_json", _canned(CRITIC_RESPONSE)
    )
    # Abstract fallback (ADR 0004): no PDF download, no chunking, no
    # chunk-ranking model load.
    monkeypatch.setattr("src.agents.reader.parse_pdf", lambda url: "")
    # Identity ranking: skips the MiniLM embedding model entirely.
    monkeypatch.setattr(
        "src.agents.search.rank_papers_by_relevance",
        lambda query, papers, top_k: list(papers)[:top_k],
    )


class TestSmokeEndToEnd:
    async def test_job_succeeds_through_production_workflow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Submit over HTTP -> real graph + real checkpointer -> succeeded.

        This is the test that fails with `NotImplementedError` when the
        compiled checkpointer has no async surface, and fails on a hung
        poll when the runner and workflow disagree about interrupts.
        """
        _patch_llm_surface(monkeypatch)

        overrides = {
            "use_mock_data": True,
            "enable_checkpointing": True,
            "checkpoint_backend": "sqlite",
            "checkpoint_db_path": str(tmp_path / "smoke-checkpoints.sqlite"),
            "enable_hitl": True,  # shipped default; job bypasses per-request
            "enable_semantic_scholar": False,
            "enable_tracing": False,
        }
        smoke_settings = settings.model_copy(update=overrides)
        assert isinstance(smoke_settings, Settings)
        # The one Settings instance is imported per-module; patch every
        # module on the request path so they agree.
        for module in (
            "src.graph.workflow",
            "src.api.runner",
            "src.api.app",
            "src.api.routes",
            "src.agents.search",
            "src.agents.reader",
            "src.agents.planner",
            "src.agents.synthesizer",
            "src.agents.critic",
        ):
            monkeypatch.setattr(f"{module}.settings", smoke_settings)

        # PRODUCTION path: no injected factory, no injected store —
        # whatever `create_app` wires by default is what gets tested.
        from src.api.app import create_app

        app = create_app()

        async with LifespanManager(app, startup_timeout=30), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit = await client.post(
                "/research", json={"query": "why do LLMs hallucinate?",
                                   "hitl_bypass": True}
            )
            assert submit.status_code == 202, submit.text
            job_id = submit.json()["job_id"]

            deadline = asyncio.get_event_loop().time() + 30.0
            body: dict[str, Any] = {}
            while asyncio.get_event_loop().time() < deadline:
                resp = await client.get(f"/research/{job_id}")
                assert resp.status_code == 200
                body = resp.json()
                if body["status"] in ("succeeded", "failed", "cancelled"):
                    break
                await asyncio.sleep(0.05)

            assert body.get("status") == "succeeded", (
                f"job ended {body.get('status')!r}: "
                f"{body.get('error_type')}: {body.get('error')}"
            )
            assert body["result"], "succeeded job must carry a report"
            assert "Hallucination" in body["result"]
            assert body["quality_score"] == pytest.approx(0.88)
            # One full pipeline pass, no double execution.
            assert body["iterations"] == 1
