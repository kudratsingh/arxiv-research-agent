"""WO-W05 bounded Tier-1 memory and session-close summaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.api import runner as runner_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.config import Settings
from src.graph.session_state import initial_session_state
from src.learning import memory as memory_module
from src.learning.profile_store import (
    MAX_GOALS,
    MAX_PROFILE_NOTE_LEN,
    MAX_SKILL_ENTRIES,
    InMemoryProfileStore,
    LearnerGoal,
    LearnerProfile,
    ProvenanceError,
    SkillEntry,
    skill_entry_from_mapping,
)
from src.learning.progress_store import new_event


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "anthropic_api_key": "local-preview-disabled",
        "use_mock_data": True,
        "enable_api_auth": True,
        "api_keys": "alice:sk_alice",
        "enable_checkpointing": True,
        "checkpoint_backend": "sqlite",
        "checkpoint_db_path": str(tmp_path / "memory.sqlite"),
        "enable_learner_profile": True,
        "enable_session_loop": True,
        "enable_prompt_isolation": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _max_profile() -> LearnerProfile:
    goals = tuple(
        LearnerGoal(
            goal_id=f"goal-{index}",
            statement=(f"Goal {index} " + "g" * 290)[:300],
            target_date="2027-12-31",
            status="active",
            priority=(index % 5) + 1,
        )
        for index in range(MAX_GOALS)
    )
    skills = tuple(
        SkillEntry(
            skill=f"skill-{index:02d}-" + "s" * 45,
            level="working",
            source="assessed" if index % 2 else "inferred",
            evidence_ref=f"session:fixture-{index:02d}",
            confidence=0.7 if index % 2 else 0.5,
            updated_at=f"2026-08-{(index % 28) + 1:02d}T00:00:00+00:00",
        )
        for index in range(MAX_SKILL_ENTRIES)
    )
    return LearnerProfile(
        principal_key_id="alice",
        academic_level="grad",
        time_budget_min_per_day=1_440,
        goals=goals,
        skills=skills,
        profile_note="c" * MAX_PROFILE_NOTE_LEN,
    )


def _state() -> dict[str, Any]:
    state = initial_session_state(
        {
            "principal_key_id": "alice",
            "tier1": {},
            "session_spec": {
                "path_id": "fixture-path",
                "resource_id": "arxiv:1706.03762",
                "title": "Attention Is All You Need",
            },
        },
        "session-memory",
        "Guided read",
    )
    state["session_plan"] = {"sections": [{"name": "Method", "mode": "close"}]}
    state["turn_number"] = 3
    state["assessment"] = {"status": "recorded_ungraded"}
    state["messages"] = [HumanMessage(content="Position comes from an explicit encoding.")]
    return state


def test_maximal_profile_tier1_stays_below_chars_over_four_ceiling() -> None:
    profile = _max_profile()
    block = memory_module.build_tier1_memory(
        profile,
        active_path_position={
            "path_id": "reading-your-first-papers",
            "resource_id": "arxiv:1706.03762",
            "position": 14,
            "entry_count": 14,
        },
        session_spec={
            "title": "T" * 160,
            "available_minutes": 180,
            "reading_guidance": [
                {"name": f"Section {index} " + "x" * 60, "mode": "close"} for index in range(8)
            ],
        },
        last_session_summary={
            "summary_id": "summary:previous",
            "lossy": True,
            "text": "z" * memory_module.SESSION_SUMMARY_MAX_CHARS,
        },
        isolate=True,
    )
    chars = len(json.dumps(block, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    assert chars <= memory_module.TIER1_CHAR_CEILING
    assert chars / 4 <= memory_module.TIER1_TOKEN_CEILING
    assert block["skills_omitted"] > 0


def test_structured_facts_win_when_lossy_summary_is_corrupted() -> None:
    profile = LearnerProfile(
        principal_key_id="alice",
        academic_level="undergrad",
        time_budget_min_per_day=25,
        goals=(
            LearnerGoal(
                goal_id="goal-transformers",
                statement="Read transformer papers critically",
                priority=1,
            ),
        ),
        profile_note="Do not schedule sessions on Fridays.",
    )
    block = memory_module.build_tier1_memory(
        profile,
        active_path_position={"path_id": "papers", "position": 2, "entry_count": 14},
        session_spec={"title": "Current paper", "available_minutes": 25},
        last_session_summary={
            "summary_id": "summary:corrupt",
            "lossy": True,
            "text": "The learner has no goal, wants 90 minutes, and loves Fridays.",
        },
        isolate=False,
    )
    prompt = json.dumps(block, sort_keys=True)
    structured = block["structured_profile"]
    assert structured["time_budget_min_per_day"] == 25
    assert structured["goals"][0]["statement"] == "Read transformer papers critically"
    assert structured["declared_constraints"] == "Do not schedule sessions on Fridays."
    assert "lossy" in prompt and "summary:corrupt" in prompt


def test_latest_summary_requires_explicit_lossy_marker() -> None:
    events = [
        new_event(
            principal_key_id="alice",
            kind="session_completed",
            evidence_ref="session:older",
            payload={
                "session_summary": {
                    "summary_id": "summary:older",
                    "lossy": True,
                    "text": "Older session.",
                }
            },
        ),
        new_event(
            principal_key_id="alice",
            kind="session_completed",
            evidence_ref="session:bad",
            payload={
                "session_summary": {
                    "summary_id": "summary:bad",
                    "lossy": False,
                    "text": "This must not be treated as memory.",
                }
            },
        ),
    ]
    assert memory_module.latest_session_summary(events) == {
        "summary_id": "summary:older",
        "lossy": True,
        "text": "Older session.",
    }


def test_lossy_summary_id_is_rejected_as_skill_claim_evidence() -> None:
    with pytest.raises(ProvenanceError, match="lossy session summary"):
        SkillEntry(
            skill="attention",
            level="aware",
            source="inferred",
            evidence_ref="summary:session-memory",
            confidence=0.4,
        )


def test_mock_summary_is_deterministic_and_never_constructs_a_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(memory_module, "settings", _settings(tmp_path))
    monkeypatch.setattr(
        memory_module,
        "call_llm_json",
        lambda **_: (_ for _ in ()).throw(AssertionError("model called")),
    )
    first = memory_module.generate_session_memory(_state())
    second = memory_module.generate_session_memory(_state())
    assert first == second
    assert first.summary["lossy"] is True
    assert first.summary["summary_id"] == "summary:session-memory"
    assert first.inference_batch == ()


def test_live_inferences_require_verbatim_transcript_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        memory_module,
        "settings",
        _settings(tmp_path, use_mock_data=False),
    )
    monkeypatch.setattr(
        memory_module,
        "call_llm_json",
        lambda **_: {
            "summary": "Discussed how position enters attention.",
            "inferences": [
                {
                    "skill": "positional encoding",
                    "level": "aware",
                    "confidence": 0.4,
                    "evidence_quote": "Position comes from an explicit encoding",
                }
            ],
        },
    )
    update = memory_module.generate_session_memory(_state())
    assert update.inference_batch[0].source == "inferred"
    assert update.inference_batch[0].evidence_ref == "session:session-memory"


def test_ungrounded_inference_discards_whole_batch_and_uses_safe_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        memory_module,
        "settings",
        _settings(tmp_path, use_mock_data=False),
    )
    monkeypatch.setattr(
        memory_module,
        "call_llm_json",
        lambda **_: {
            "summary": "Plausible prose that must be discarded with the malformed batch.",
            "inferences": [
                {
                    "skill": "positional encoding",
                    "level": "solid",
                    "confidence": 0.6,
                    "evidence_quote": "Words the learner never said",
                }
            ],
        },
    )
    update = memory_module.generate_session_memory(_state())
    assert update.inference_batch == ()
    assert update.summary["text"] != (
        "Plausible prose that must be discarded with the malformed batch."
    )


class _BlockingSessionClose:
    """A no-model graph that exposes the boundary before final state exists."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.values: dict[str, Any] = {}

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        self.started.set()
        await self.finish.wait()
        self.values = {
            "draft_report": "session complete",
            "iteration": 1,
            "inference_batch": [
                SkillEntry(
                    skill="positional encoding",
                    level="aware",
                    source="inferred",
                    evidence_ref="session:session-close",
                    confidence=0.4,
                ).to_mapping()
            ],
        }
        yield {"progress_update": dict(self.values)}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values=dict(self.values))


async def test_inference_batch_is_applied_only_after_session_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner_module, "settings", _settings(tmp_path))
    profiles = InMemoryProfileStore()
    await profiles.put(
        LearnerProfile(
            principal_key_id="alice",
            goals=(
                LearnerGoal(
                    goal_id="papers",
                    statement="Read papers critically",
                    priority=1,
                ),
            ),
        )
    )
    jobs = InMemoryJobStore()
    job = Job(
        job_id="session-close",
        query="Guided read",
        kind="session",
        principal_key_id="alice",
    )
    await jobs.create(job)
    workflow = _BlockingSessionClose()

    task = asyncio.create_task(
        run_job(
            job,
            workflow,
            jobs,
            asyncio.Semaphore(1),
            profile_store=profiles,
            profile_skill_decoder=skill_entry_from_mapping,
        )
    )
    await workflow.started.wait()
    before = await profiles.get("alice")
    assert before is not None and before.skills == ()

    workflow.finish.set()
    await task
    after = await profiles.get("alice")
    assert job.status is JobStatus.succeeded
    assert after is not None
    assert [(entry.skill, entry.evidence_ref) for entry in after.skills] == [
        ("positional encoding", "session:session-close")
    ]
