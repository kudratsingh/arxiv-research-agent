"""The compiled graph's shape, on record, for the shapes that predate CAP-02.

`src/graph/workflow.py` grows a third shape in this work order, chosen by
a new `research_policy` selector rather than by `enable_supervisor`. The
claim that carries the change is that nothing else moved: with the
selector at its default the compiled node set and edge listing are the
ones this repository already shipped.

A claim like that is only worth something if the "before" was written
down *before*. This file and its fixture were committed against the
unmodified `_build_graph_shape`, in their own commit, so the diff of the
work order proves the baseline rather than asserting it — a golden
regenerated in the same commit as the change it guards is a photograph
of the change, not of what preceded it.

Three configurations, because the legacy dispatch has three reachable
answers: the shipped default, the supervisor loop, and the supervisor
loop with both optional action nodes on (arm D of
`docs/agent-engineering/07-first-policy-experiment.md`). The listing is
read off `CompiledStateGraph.get_graph()` — LangGraph's own view of what
it compiled, which expands a conditional edge into one edge per branch
target and therefore sees a router whose map lost an entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.graph.workflow as workflow_module
from src.config import settings

pytestmark = pytest.mark.unit

#: The listing on record. Regenerate deliberately, never as a reflex:
#: `python -c` over `render_listing()` writes it, and a diff here is a
#: graph-shape change that belongs in a PR body.
GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "graph" / "legacy-shapes.txt"
)

#: Name -> settings overrides. `enable_checkpointing` is off in all
#: three because a saver is a connection rather than a shape: it changes
#: what `compile()` persists, never which nodes or edges exist, and
#: leaving it on would open a SQLite file per test.
CONFIGURATIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("legacy / default (fixed pipeline)", {}),
    ("legacy / supervisor loop", {"enable_supervisor": True}),
    (
        "legacy / supervisor loop + verifier + query refiner",
        {
            "enable_supervisor": True,
            "enable_verifier": True,
            "enable_query_refiner": True,
        },
    ),
)


def compile_listing(**overrides: Any) -> str:
    """Node set and edge listing of the graph these settings compile to.

    Sorted, so the text is a function of the graph rather than of the
    order `add_node` happened to be called in — a reordering that keeps
    every edge is not a shape change and should not read as one.
    """
    patched = settings.model_copy(
        update={"enable_checkpointing": False, **overrides}
    )
    original = workflow_module.settings
    workflow_module.settings = patched  # type: ignore[misc]
    try:
        app = workflow_module.build_workflow(enable_hitl=False)
    finally:
        workflow_module.settings = original  # type: ignore[misc]
    try:
        graph = app.get_graph()
    finally:
        app._checkpointer_exit_stack.close()

    lines = [f"nodes: {', '.join(sorted(graph.nodes))}", "edges:"]
    rendered = sorted(
        f"  {edge.source} -> {edge.target}"
        f"{' [conditional]' if edge.conditional else ''}"
        for edge in graph.edges
    )
    lines.extend(rendered)
    return "\n".join(lines)


def render_listing() -> str:
    """The whole fixture: every configuration under its own heading."""
    blocks = [
        f"## {name}\n{compile_listing(**overrides)}"
        for name, overrides in CONFIGURATIONS
    ]
    return "\n\n".join(blocks) + "\n"


class TestTheLegacyShapesAreTheShapesOnRecord:
    def test_the_compiled_listing_matches_the_fixture(self) -> None:
        """The whole point of the file: default settings did not move.

        A failure here is either a real change to the fixed pipeline or
        the supervisor loop — in which case the fixture moves in the
        same PR, with the reason in the body — or a new shape that
        leaked into the legacy dispatch, which is the defect this test
        exists to catch.
        """
        assert render_listing() == GOLDEN_PATH.read_text(encoding="utf-8")

    def test_the_default_configuration_has_no_verification_node(self) -> None:
        """Stated separately because it is the load-bearing half.

        The fixture would still match if `verify` were added to every
        shape at once; this says the shipped default reaches the critic
        straight out of the synthesizer, which is what the scripted
        research tier's trajectory assertion depends on.
        """
        listing = compile_listing()
        assert "verify" not in listing
        assert "repair" not in listing
        assert "  synthesizer -> critic" in listing
