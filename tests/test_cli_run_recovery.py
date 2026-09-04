"""CLI failure recovery + the canonical initial state (ADR 0052).

Two findings in `src/main.py`:

- **A finished report was thrown away when a later node failed.** The
  synthesizer runs before the critic and the verifier, so a failure in
  a later node happens with a complete `draft_report` already in the
  checkpoint — and the CLI simply re-raised, with nothing on its
  surface that reads a checkpoint. `run` now salvages that draft to
  `outputs/<run_id>-recovered.md` and logs the `thread_id` on *every*
  failure so manual recovery stays possible when the salvage itself
  cannot run.
- **A third, ten-keys-stale copy of the initial `ResearchState`.**
  `ResearchState` is a total TypedDict, so the CLI's literal was
  already invalid against its own schema and only survived because
  every consumer reads through `.get()`.

Mutation-checked. Deleting the `_recover_draft_report` call from the
`except` block fails `test_recovers_a_finished_report_from_the_checkpoint`;
dropping `thread_id` from the failure record fails
`test_thread_id_is_logged_even_when_nothing_is_recoverable`; removing
a key from `initial_research_state` fails
`test_canonical_initializer_covers_every_state_key`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from src import main as main_module
from src.graph.state import ResearchState, initial_research_state

pytestmark = [pytest.mark.unit, pytest.mark.fault]


class _StubApp:
    """Stands in for the compiled graph.

    `invoke` either returns a final state or raises; `get_state`
    returns whatever the checkpoint is meant to hold at that moment.
    """

    def __init__(
        self,
        *,
        final_state: dict[str, Any] | None = None,
        error: Exception | None = None,
        checkpoint: dict[str, Any] | None = None,
        get_state_error: Exception | None = None,
    ) -> None:
        self.final_state = final_state
        self.error = error
        self.checkpoint = checkpoint
        self.get_state_error = get_state_error
        self.invoked_with: dict[str, Any] | None = None
        self.get_state_config: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.invoked_with = state
        if self.error is not None:
            raise self.error
        assert self.final_state is not None
        return self.final_state

    def get_state(self, config: dict[str, Any]) -> Any:
        self.get_state_config = config
        if self.get_state_error is not None:
            raise self.get_state_error

        class _Snapshot:
            values = self.checkpoint or {}

        return _Snapshot()


@pytest.fixture
def outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the CLI's output directory into the tmp tree."""
    dest = tmp_path / "outputs"
    monkeypatch.setattr(main_module, "OUTPUT_DIR", dest)
    return dest


def _install(monkeypatch: pytest.MonkeyPatch, app: _StubApp) -> None:
    monkeypatch.setattr(main_module, "build_workflow", lambda **_kw: app)


class TestCheckpointRecovery:
    def test_recovers_a_finished_report_from_the_checkpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The expensive case: the report exists, a later node blew up."""
        report = "# Findings\n\nRAG reduces hallucination.\n"
        app = _StubApp(
            error=RuntimeError("critic exploded"),
            checkpoint={"draft_report": report},
        )
        _install(monkeypatch, app)

        with (
            caplog.at_level(logging.INFO, logger="src.main"),
            pytest.raises(RuntimeError, match="critic exploded"),
        ):
            main_module.run("q", run_id="run123")

        salvaged = outputs / "run123-recovered.md"
        assert salvaged.read_text() == report
        # The operator is told where it went, on stderr, next to the
        # traceback they are already reading.
        assert str(salvaged) in capsys.readouterr().err

        failed = [r for r in caplog.records if r.message == "run_failed"]
        assert len(failed) == 1
        assert failed[0].thread_id == "run123"  # type: ignore[attr-defined]
        assert failed[0].recovered_path == str(salvaged)  # type: ignore[attr-defined]

    def test_recovery_reads_the_failed_run_s_own_thread(
        self, monkeypatch: pytest.MonkeyPatch, outputs: Path
    ) -> None:
        """The checkpoint is per-thread; the wrong `thread_id` reads as
        empty rather than as an error, which would look like "nothing
        to recover" for every run."""
        app = _StubApp(
            error=RuntimeError("boom"), checkpoint={"draft_report": "x"}
        )
        _install(monkeypatch, app)

        with pytest.raises(RuntimeError):
            main_module.run("q", run_id="run123")

        assert app.get_state_config == {"configurable": {"thread_id": "run123"}}

    def test_nothing_is_written_when_the_draft_is_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An early failure (the planner, the search) has no report to
        salvage — writing an empty file would be worse than nothing."""
        app = _StubApp(
            error=RuntimeError("no papers"), checkpoint={"draft_report": "   "}
        )
        _install(monkeypatch, app)

        with pytest.raises(RuntimeError):
            main_module.run("q", run_id="run123")

        assert not (outputs / "run123-recovered.md").exists()
        err = capsys.readouterr().err
        assert "no recoverable report" in err
        # Still recoverable by hand: the thread_id is the only handle.
        assert "run123" in err

    def test_thread_id_is_logged_even_when_nothing_is_recoverable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app = _StubApp(error=RuntimeError("boom"), checkpoint={})
        _install(monkeypatch, app)

        with (
            caplog.at_level(logging.INFO, logger="src.main"),
            pytest.raises(RuntimeError),
        ):
            main_module.run("q", run_id="run123")

        failed = [r for r in caplog.records if r.message == "run_failed"]
        assert failed[0].thread_id == "run123"  # type: ignore[attr-defined]
        assert failed[0].recovered_path is None  # type: ignore[attr-defined]

    def test_an_unreadable_checkpoint_does_not_mask_the_real_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """`get_state` raises when checkpointing is off entirely. The
        salvage runs from an `except` block, so anything it raises
        would replace the exception the caller came to see."""
        app = _StubApp(
            error=ValueError("the real failure"),
            get_state_error=RuntimeError("no checkpointer configured"),
        )
        _install(monkeypatch, app)

        with (
            caplog.at_level(logging.WARNING, logger="src.main"),
            pytest.raises(ValueError, match="the real failure"),
        ):
            main_module.run("q", run_id="run123")

        unavailable = [
            r
            for r in caplog.records
            if r.message == "run_recovery_state_unavailable"
        ]
        assert len(unavailable) == 1
        assert unavailable[0].thread_id == "run123"  # type: ignore[attr-defined]

    def test_a_failure_before_the_graph_exists_still_reports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """`build_workflow` itself can fail (a bad backend URL). There
        is no `app` to read a checkpoint from, and the failure path
        must not turn that into an AttributeError."""

        def _explode(**_kw: Any) -> Any:
            raise RuntimeError("bad checkpointer url")

        monkeypatch.setattr(main_module, "build_workflow", _explode)

        with (
            caplog.at_level(logging.INFO, logger="src.main"),
            pytest.raises(RuntimeError, match="bad checkpointer url"),
        ):
            main_module.run("q", run_id="run123")

        failed = [r for r in caplog.records if r.message == "run_failed"]
        assert failed[0].thread_id == "run123"  # type: ignore[attr-defined]

    def test_a_successful_run_writes_no_recovery_file(
        self, monkeypatch: pytest.MonkeyPatch, outputs: Path
    ) -> None:
        app = _StubApp(final_state={"draft_report": "# Report", "iteration": 1})
        _install(monkeypatch, app)

        assert main_module.run("q", run_id="run123") == "# Report"
        assert not (outputs / "run123-recovered.md").exists()


class TestCanonicalInitialState:
    """One initializer, not three drifting literals."""

    def test_canonical_initializer_covers_every_state_key(self) -> None:
        """`ResearchState` is total: a missing key is a schema
        violation, not a default."""
        state = initial_research_state("q", "run123")
        assert set(state) == set(ResearchState.__annotations__)

    def test_cli_invokes_the_graph_with_the_canonical_state(
        self, monkeypatch: pytest.MonkeyPatch, outputs: Path
    ) -> None:
        """The finding was that `make run` and the same query submitted
        to the API started from different states."""
        app = _StubApp(final_state={"draft_report": "# Report"})
        _install(monkeypatch, app)

        main_module.run("what is X?", run_id="run123")

        assert app.invoked_with == initial_research_state("what is X?", "run123")

    @pytest.mark.parametrize(
        "module_path", ["src.api.runner", "src.eval.runner"]
    )
    def test_runner_states_have_not_drifted_from_the_canonical_one(
        self, module_path: str
    ) -> None:
        """Drift guard for the two copies this lane does not own.

        The intended end state is that both call
        `initial_research_state` and their private `_initial_state`
        disappears — this test skips itself once that happens, and
        until then it fails the moment the shapes diverge again.
        """
        import importlib

        module = importlib.import_module(module_path)
        builder = getattr(module, "_initial_state", None)
        if builder is None:
            pytest.skip(f"{module_path} adopted the canonical initializer")

        assert dict(builder("q", "run123")) == dict(
            initial_research_state("q", "run123")
        )
