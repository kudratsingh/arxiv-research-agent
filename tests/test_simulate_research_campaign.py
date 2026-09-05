"""The research lane's free gate, driven as a campaign (WO-C1, ADR 0075).

`tests/test_simulate_research.py` tests the tier's pieces. This file runs
the thing itself: the real compiled research graph, the real CLI, the
real durable record layout, the real summary files, and then the same
`scripted_tier_check` invocation CI would run over the result.

It is the research lane's counterpart of the zero-spend proof the
learning lane has had since WO-W10 — and, unlike that one, it has
something extra to prove. The session graph runs free on mock mode
alone; the research graph does not, because `USE_MOCK_DATA` never
touches `src/llm.py` (`tests/e2e/conftest.py` says so at length). So the
assertions here are not only "it cost nothing" but "it cost nothing
*and the graph really ran*": the bound cost accumulator proves the
first, `scripted_llm_calls` proves the second, and neither is worth much
without the other. A campaign short-circuited to twenty empty records
would pass every cost assertion ever written.

**Why the integration tier and not `tests/e2e/`.** The e2e tier is
deliberately bounded and its size is a claim `README.md` makes and
`tests/test_documented_claims.py` enforces as an equality; this work
order does not own `README.md`. The tier this file wants is in any case
`integration` on `docs/testing.md`'s own terms — it drives one
subsystem's compiled graph in process, the way
`tests/test_guided_session_graph.py` drives the session graph — and it
runs inside the merge gate's `-m "not e2e"` selection, which is where a
per-PR gate's own proof belongs. Settings are installed here rather than
borrowed from the e2e fixture for the same reason.

The tier's own limitation is not hidden by this file either. What is
asserted below is the pipeline — the trajectory, the fan-out, the
citation parser, the claim set — never report quality, because the
report's words are the harness's.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.config import settings as real_settings
from src.eval import scripted_tier_check as check
from src.eval import simulate_research as sim
from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.eval.provenance import PROVENANCE_KEY
from src.observability.costs import RunCosts, start_cost_tracking

pytestmark = pytest.mark.integration

#: Modules that bind `src.config.settings` and sit on this campaign's
#: path. The union, not the per-test minimum, for the reason
#: `tests/e2e/conftest.py` gives at length: a module left off the list
#: keeps the shipped default, which is a silent behaviour split rather
#: than an error. `src.eval.provenance` is on it because it stamps
#: `mock_mode` on every row, and `src.eval.simulate_research` because it
#: reads mock mode to decide whether it may start at all.
SETTINGS_CONSUMERS: tuple[str, ...] = (
    "src.agents.critic",
    "src.agents.planner",
    "src.agents.reader",
    "src.agents.search",
    "src.agents.synthesizer",
    "src.eval.provenance",
    "src.eval.simulate_research",
    "src.graph.workflow",
)


@pytest.fixture
def install_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Rebind a mock-mode `settings` across every module on the path.

    `tests/conftest.py` scrubs every variable `Settings` reads before
    collection, so `USE_MOCK_DATA=true` in the shell never reaches a
    test. This is the mechanism; the Makefile's pin is the statement of
    intent.
    """

    def _install(**overrides: Any) -> Settings:
        merged: dict[str, Any] = {
            "use_mock_data": True,
            "enable_tracing": False,
            "enable_semantic_scholar": False,
            "enable_checkpointing": False,
            "enable_supervisor": False,
            **overrides,
        }
        patched = real_settings.model_copy(update=merged)
        assert isinstance(patched, Settings)
        for module in SETTINGS_CONSUMERS:
            monkeypatch.setattr(f"{module}.settings", patched)
        return patched

    return _install


@pytest.fixture
def spend_ledger() -> Iterator[RunCosts]:
    """Bind a cost accumulator around the test and prove it never moved.

    The campaign binds its own accumulator per record, so this one sees
    only spend the *test* made around it — the same split
    `tests/e2e/conftest.py` describes for `run_job`. The per-row
    `llm_calls` assertions are the proof about the campaign; this is the
    backstop for everything else in the context.
    """
    costs = start_cost_tracking()
    yield costs
    assert costs.total_cost_usd == 0.0
    assert costs.call_count == 0


@pytest.fixture
def usd() -> Callable[[float | None], str]:
    """Render a cost the way every report in this repository renders it."""

    def _format(amount: float | None) -> str:
        return f"${(amount or 0.0):.4f}"

    return _format


#: Queries the campaign runs here. A subset, and the subset is the
#: point: this tier's per-query behaviour is identical by construction
#: (the corpus is the same five papers for every query), so three
#: queries prove the campaign machinery and twenty would only prove that
#: a loop runs twenty times. `--expected-sessions` is what lets the
#: check assert completeness against the subset rather than the whole
#: benchmark, and the whole benchmark is asserted in
#: `tests/test_simulate_research.py` against the committed baseline.
SUBSET = [q["query_id"] for q in BENCHMARK_QUERIES[:3]]


def _rows(output_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (output_dir / "summary.jsonl").read_text().splitlines()
        if line.strip()
    ]


class TestScriptedResearchCampaign:
    def test_a_campaign_runs_the_whole_graph_and_costs_exactly_nothing(
        self,
        install_settings: Callable[..., Any],
        tmp_path: Path,
        spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The gate, end to end, in the form the Makefile target runs it.

        Deliberately *not* using `research_llm_surface`: that fixture is
        the e2e tier's own way of canning the four agents, and using it
        here would test the fixture rather than the tier. The tier
        installs its own surface, and this test is what says so.
        """
        install_settings(
            enable_checkpointing=False,
            enable_supervisor=False,
            checkpoint_db_path=str(tmp_path / "scripted-research.sqlite"),
        )
        output_dir = tmp_path / "campaign"

        exit_code = sim.main(
            ["--queries", ",".join(SUBSET), "--output-dir", str(output_dir)]
        )
        assert exit_code == 0, "the scripted campaign must complete cleanly"

        rows = _rows(output_dir)
        assert [row["query_id"] for row in rows] == SUBSET
        assert (output_dir / "summary.md").read_text().strip()
        for query_id in SUBSET:
            assert (output_dir / "queries" / f"{query_id}.json").is_file()

        for row in rows:
            # The trajectory, which is the assertion this tier exists
            # for: a graph that skipped the reader or looped the
            # synthesizer still produces a non-empty report.
            assert row["trajectory"] == list(sim.FIXED_PIPELINE)
            assert row["expectation_failures"] == 0
            # Five mock papers, each read, each cited, each resolving
            # against the corpus the run itself retrieved.
            assert row["papers"] == 5
            assert row["analyses"] == 5
            assert row["citations"] == 5
            assert row["citation_resolution_rate"] == 1.0
            assert row["claims_decided"] == 5
            assert row["quote_verbatim_reason"] == "no_quotes"
            # Zero spend, and proof the graph ran anyway. Neither number
            # means much on its own.
            assert usd(row["total_cost_usd"]) == "$0.0000"
            assert row["llm_calls"] == 0
            assert row["judge_llm_calls"] == 0
            assert row["scripted_llm_calls"] == 8  # 1 + 5 readers + 1 + 1
            assert row["tier"] == sim.RESEARCH_SCRIPTED_TIER
            assert row[PROVENANCE_KEY]["mock_mode"] is True

        # The backstop ledger. See the fixture: the campaign binds its
        # own accumulator per record, so the per-row `llm_calls` above
        # are the proof about the campaign and this is the proof about
        # everything the test did around it.
        assert usd(spend_ledger.total_cost_usd) == "$0.0000"
        assert spend_ledger.call_count == 0

    def test_the_check_ci_runs_passes_over_the_campaign_it_produced(
        self,
        install_settings: Callable[..., Any],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The second half of the CI step, over the first half's output.

        Running the campaign and running the check are two commands, and
        a test that only ran the first would leave the gate's own
        invocation — its lane flag, its record count, its exit code —
        unexercised outside a unit test's hand-built rows.
        """
        install_settings(enable_checkpointing=False, enable_supervisor=False)
        output_dir = tmp_path / "campaign"
        assert sim.main(["--queries", ",".join(SUBSET), "--output-dir", str(output_dir)]) == 0

        exit_code = check.main(
            [
                str(output_dir / "summary.jsonl"),
                "--lane",
                "research",
                "--expected-sessions",
                str(len(SUBSET)),
            ]
        )
        assert exit_code == 0
        assert "Scripted tier OK" in capsys.readouterr().out

    def test_a_truncated_campaign_fails_the_check(
        self,
        install_settings: Callable[..., Any],
        tmp_path: Path,
    ) -> None:
        """Green on a shrunken denominator is the dangerous kind of green.

        The mutation is the one that actually happens: a batch that died
        partway, leaving fewer records than the benchmark has queries.
        """
        install_settings(enable_checkpointing=False, enable_supervisor=False)
        output_dir = tmp_path / "campaign"
        assert sim.main(["--queries", SUBSET[0], "--output-dir", str(output_dir)]) == 0

        assert (
            check.main(
                [
                    str(output_dir / "summary.jsonl"),
                    "--lane",
                    "research",
                    "--expected-sessions",
                    str(len(BENCHMARK_QUERIES)),
                ]
            )
            == 1
        )

    def test_a_resumed_campaign_reuses_its_records(
        self,
        install_settings: Callable[..., Any],
        tmp_path: Path,
    ) -> None:
        """ADR 0050's crash-safety, inherited rather than reimplemented."""
        install_settings(enable_checkpointing=False, enable_supervisor=False)
        output_dir = tmp_path / "campaign"
        assert sim.main(["--queries", SUBSET[0], "--output-dir", str(output_dir)]) == 0
        first = _rows(output_dir)[0]

        assert (
            sim.main(
                [
                    "--queries",
                    ",".join(SUBSET),
                    "--output-dir",
                    str(output_dir),
                    "--resume",
                ]
            )
            == 0
        )
        rows = _rows(output_dir)
        assert [row["query_id"] for row in rows] == SUBSET
        # The reused record is the original one, not a re-run: its own
        # run id survives, which is what "skipped, not re-paid" means.
        assert rows[0]["record_id"] == first["record_id"]

    def test_writing_into_a_populated_directory_is_refused(
        self,
        install_settings: Callable[..., Any],
        tmp_path: Path,
    ) -> None:
        install_settings(enable_checkpointing=False, enable_supervisor=False)
        output_dir = tmp_path / "campaign"
        assert sim.main(["--queries", SUBSET[0], "--output-dir", str(output_dir)]) == 0
        assert sim.main(["--queries", SUBSET[0], "--output-dir", str(output_dir)]) == 2
