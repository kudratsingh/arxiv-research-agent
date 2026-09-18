"""`python -m src.campaign plan|dry-run|run|rehearse|resume|status|report|smoke`.

Eight verbs, and the split between them is the work order's: **`plan`,
`dry-run`, `rehearse`, `resume`, `status` and `report` have no execution
side effects, and `run` and `smoke` are the two that do.** `dry-run` enumerates
every planned episode with its zero-cost status and writes nothing —
unless `--artifact` names a file, which is the one thing it writes and is
a projection of the plan rather than a campaign directory; `plan`
materializes the campaign directory — manifest, lock, arm configs, task
set and the denominator ledger — and still runs nothing; `resume`
reopens a materialized campaign under the same lock and cap and reports
what is left; `status` reconciles the ledger against the receipts on
disk.

`rehearse` walks the funded path of a materialized campaign — approval
check, ledger open, episode manifest seal against the real compiled
graph, provider credential, provider client — and stops at the first
door a credential opens, naming what is still owed. It runs no episode
and makes no call; `src/campaign/rehearse.py` says why each step is the
real one.

`report` is the pass after `run`: it reads the campaign's sealed
records and the durable trajectories they point at and writes one
markdown document — quality per arm, cost and latency per arm, the
error-taxonomy counts, the denominators and the lineage. It runs no
episode, calls no model, and writes nothing into the campaign directory.

`run` executes the pending episodes of a campaign that was already
planned. It is deliberately a *separate* verb from `plan`: the campaign
directory, the sealed protocol and the denominator ledger all exist
before the first episode runs, so an operator can read the design and the
cap before authorizing anything to execute against them. Resume is not a
sixth verb — `run` always skips episodes that already hold a terminal
`completion.json`, so running a second time after an interruption *is*
the resume, under the same lock and the same cap.

`smoke` is the eighth verb and the newest (LE-S, EL-04). It runs
[ADR 0090](../../docs/decisions/0090-anthropic-sdk-1x.md)'s five
CAP-06 probes against the real provider under one accumulator and one
`--cap-usd`, and writes a JSON receipt saying which of the five are now
verified. It is not a campaign and runs no episode, but it **cannot
bypass approval**: it verifies an owner's record against its own campaign
id and stage before a client is constructed, exactly as `run` does.

The four read-only verbs compile no graph and construct no provider. Arm
capability is left `unverified` at plan time and proved at seal time by
the process that actually has a compiled graph, which is the only place
the evidence exists — and `run` is that process. `rehearse` is the fifth
verb with no execution side effects and the exception to the first
sentence: it *does* compile a graph and *does* reach the provider's
constructor, on purpose, because proving the funded path is complete up
to the credential is the whole of what it is for.

Every verb prints JSON on stdout so the output is usable by W11's
qualification report without a parser for prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.campaign.approval import LocalApprovalRecordBackend
from src.campaign.arms import ARM_IDS, ArmId
from src.campaign.errors import CampaignError
from src.campaign.planner import (
    DEFAULT_OUTPUT_ROOT,
    CampaignRequest,
    campaign_status,
    default_campaign_budget,
    default_episode_budget,
    dry_run,
    plan_campaign,
    preflight_approval,
    rebuild_plan,
    resume_campaign,
    status_counts,
    suite_case_ids,
    write_campaign,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.registry import LocalRegistry

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.campaign",
        description=(
            "Plan, dry-run, resume and report on a registry-locked research "
            "campaign. plan and dry-run never run an episode or contact a "
            "provider."
        ),
    )
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "dry-run",
            "run",
            "rehearse",
            "resume",
            "status",
            "report",
            "smoke",
        ),
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=Path("eval_registry"),
        help="Registry tree to resolve the suite from. Default: eval_registry/",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(DEFAULT_OUTPUT_ROOT),
        help=f"Directory holding campaign roots. Default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--suite",
        default="research-policy-v1",
        help="Benchmark suite id. Default: research-policy-v1",
    )
    parser.add_argument(
        "--cases",
        default="",
        help=(
            "Comma-separated case ids. Default: every case in the suite's "
            "task set, in registry order."
        ),
    )
    parser.add_argument(
        "--arms",
        default=",".join(ARM_IDS),
        help=(
            "Comma-separated arms. Default: all five. Arm E is probed like "
            "every other arm; it runs when this checkout holds its four "
            "settings and is capability_missing when it does not (ADR 0091)."
        ),
    )
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per condition.")
    parser.add_argument("--seed", type=int, default=0, help="Interleaving seed.")
    parser.add_argument(
        "--corpus-mode",
        choices=("snapshot", "live"),
        default="snapshot",
        help=(
            "Aggregation boundary. A snapshot campaign and a live campaign "
            "never share a summary."
        ),
    )
    parser.add_argument("--stage", default="stage-0-qualification")
    parser.add_argument("--protocol-id", default="research-policy-v1-stage-0")
    parser.add_argument(
        "--approval-records",
        type=Path,
        default=None,
        help=(
            "JSON file of external approval records. Required before any "
            "chargeable campaign; possessing an API key is never approval."
        ),
    )
    parser.add_argument("--approval-id", default=None)
    parser.add_argument(
        "--episode-workflow-usd",
        default="0.000000",
        help="Approved workflow spend per episode. Default: zero.",
    )
    parser.add_argument(
        "--episode-judge-usd",
        default="0.000000",
        help="Approved judge spend per episode. Default: zero.",
    )
    parser.add_argument(
        "--campaign-usd",
        default="0.000000",
        help="Approved aggregate cap. Default: zero.",
    )
    parser.add_argument(
        "--campaign-id", default=None, help="For run, resume, status and report."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Where report writes its markdown. Default: stdout. The report is "
            "derived from the records and is never written into the campaign "
            "directory."
        ),
    )
    parser.add_argument(
        "--sink-root",
        type=Path,
        default=None,
        help=(
            "Root of the durable trajectory sink for run. Default: the "
            "deployment's contract_event_sink_root."
        ),
    )
    parser.add_argument(
        "--max-episodes",
        type=int,
        default=None,
        help=(
            "Stop run after this many episodes. The remainder stay pending "
            "and stay in the denominator."
        ),
    )
    parser.add_argument(
        "--mock-judge",
        action="store_true",
        help=(
            "Run the three judge metrics through the deterministic fixture "
            "surface. Default: off. Requires USE_MOCK_DATA=true and "
            "ANTHROPIC_API_KEY=local-preview-disabled."
        ),
    )
    parser.add_argument(
        "--live-judge",
        action="store_true",
        help=(
            "Score the three judge rubrics with real model calls, under the "
            "episode's own judge allocation and a separate cost accumulator. "
            "Default: off. Refused under USE_MOCK_DATA=true or the zero-spend "
            "sentinel, and mutually exclusive with --mock-judge."
        ),
    )
    parser.add_argument(
        "--no-state-chunks",
        action="store_true",
        help=(
            "Write episode-state.json without the reader's ranked chunk text, "
            "keeping each chunk's digest, section, paper and score. Default: "
            "the chunks are kept, because a campaign that discarded them "
            "cannot be re-judged against the text its reports were written "
            "from."
        ),
    )
    parser.add_argument(
        "--cap-usd",
        default="0.000000",
        help=(
            "For smoke: the ceiling every probe runs under, bound as the "
            "effective cost cap. Must be positive and must be covered by the "
            "named approval record."
        ),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=(
            "For smoke: where the JSON receipt is written. Default: stdout "
            "only."
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=None,
        help=(
            "For dry-run: also write the plan as a publishable artifact at "
            "this path. The file carries the sealed protocol and lock "
            "digests, the arm declarations, the case set, the repeats, the "
            "zero caps and the command that produced it, and it is the only "
            "thing dry-run writes."
        ),
    )
    return parser


def _config() -> Settings:
    """The shipped settings, with the campaign's own frozen values on top.

    `model_copy` rather than a fresh `Settings()`: the campaign inherits
    whatever the deployment configured and overrides only what the arm
    table owns, which is applied per arm by `arm_settings`.

    Three values are the campaign's rather than the deployment's.
    Checkpointing is off because a campaign episode is unattended and a
    persisted thread would outlive it. The contract shadow and the
    `evaluation_only` durable sink are on because a campaign episode
    *is* the lane ADR 0083 built that member for — public benchmark
    inputs, evaluation-only consent, no user content — and an episode
    with no durable trajectory could not prove what it did. Neither
    switch can reach production capture: `capture_permitted` refuses a
    `product_operation_only` run whatever the flag says.
    """
    patched = shipped_settings.model_copy(
        update={
            "enable_checkpointing": False,
            "contract_shadow": "shadow",
            "contract_event_capture": "evaluation_only",
        }
    )
    assert isinstance(patched, Settings)
    return patched


def _case_ids(root: Path, suite: str, explicit: str) -> tuple[str, ...]:
    """Read the suite's case order from the registry, or take the operator's."""
    if explicit.strip():
        return tuple(item.strip() for item in explicit.split(",") if item.strip())
    return suite_case_ids(root, suite)


def _request(args: argparse.Namespace, config: Settings) -> CampaignRequest:
    """Turn parsed arguments into the planner's request.

    `--arms` is re-ordered into `ARM_IDS` order rather than kept as
    typed, so two operators who name the same arms get the same protocol
    digest and therefore the same campaign id.
    """
    requested = [item.strip() for item in str(args.arms).split(",") if item.strip()]
    unknown = [arm for arm in requested if arm not in ARM_IDS]
    if unknown:
        raise CampaignError(f"unknown arms: {', '.join(unknown)}")
    arms: tuple[ArmId, ...] = tuple(arm for arm in ARM_IDS if arm in requested)
    return CampaignRequest(
        protocol_id=args.protocol_id,
        stage=args.stage,
        suite_ref=suite_ref(args.registry_root, args.suite),
        case_ids=_case_ids(args.registry_root, args.suite, args.cases),
        arms=arms,
        repeats=int(args.repeats),
        corpus_mode=args.corpus_mode,
        seed=int(args.seed),
        approval_id=args.approval_id,
        episode_budget=default_episode_budget(
            config,
            arms,
            workflow_usd=args.episode_workflow_usd,
            judge_usd=args.episode_judge_usd,
        ),
        campaign_budget=default_campaign_budget(args.campaign_usd),
        output_root=str(args.output_root).strip("/") or DEFAULT_OUTPUT_ROOT,
    )


def _backend(args: argparse.Namespace) -> LocalApprovalRecordBackend:
    if args.approval_records is None:
        return LocalApprovalRecordBackend()
    return LocalApprovalRecordBackend.from_file(args.approval_records)


def main(argv: list[str] | None = None) -> int:
    """Run one verb and return its exit code.

    A refusal is `EXIT_REFUSED` with the structural fact on stderr, never
    a traceback and never a partial success: the campaign vocabulary has
    no degraded outcome for an operator to misread as one.
    """
    args = _parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return _run(args)
    except CampaignError as exc:
        print(f"Refused: {exc.detail}", file=sys.stderr)
        return EXIT_REFUSED


def _run(args: argparse.Namespace) -> int:
    """Dispatch one verb, letting a refusal propagate to `main`.

    The ordering is the module's contract in executable form: the two
    planning verbs return before `--campaign-id` is needed, and `run` and
    `report` import their heavy modules inside their own branch so the
    read-only verbs never reach the graph.
    """
    config = _config()
    root: Path = args.output_root

    if args.command in ("plan", "dry-run"):
        request = _request(args, config)
        registry = LocalRegistry(args.registry_root)
        plan = plan_campaign(config, request, resolver=registry)
        # Checked before anything is written: a 300-episode campaign should
        # not discover on episode one that its approval covers nothing.
        preflight_approval(plan, _backend(args))
        if args.command == "dry-run":
            _emit(dry_run(plan).model_dump(mode="json"))
            if args.artifact is not None:
                _emit({"artifact": str(_write_artifact(args, plan, request))})
            return EXIT_OK
        if args.artifact is not None:
            raise CampaignError(
                "--artifact belongs to dry-run: plan materializes a campaign "
                "directory under the output root, and a published artifact is "
                "a projection rather than a second copy of one"
            )
        directory = write_campaign(root, plan)
        _emit(
            {
                "campaign_id": plan.campaign_id,
                "directory": str(directory),
                "expected_episode_count": plan.manifest.payload.expected_episode_count,
                "planned_episode_count": plan.manifest.payload.planned_episode_count,
                "excluded_episode_count": plan.manifest.payload.excluded_episode_count,
                "chargeable": plan.manifest.payload.protocol.chargeable,
                "ledger": str(directory / "campaign-ledger.json"),
            }
        )
        return EXIT_OK

    if args.command == "smoke":
        # Before the `--campaign-id` gate rather than after it: the smoke
        # is not a campaign and has a campaign id of its own
        # (`SMOKE_CAMPAIGN_ID`), which is what its approval record has to
        # name. Requiring an unrelated campaign here would invite an
        # operator to point a research campaign's approval at it.
        from src.campaign.smoke import render_receipt, run_smoke

        if args.approval_id is None:
            raise CampaignError(
                "the CAP-06 smoke requires --approval-id and the "
                "--approval-records file holding it; possessing a key is "
                "never authorization to spend"
            )
        receipt = run_smoke(
            config,
            approval_id=args.approval_id,
            cap_usd=str(args.cap_usd),
            approval_backend=_backend(args),
            receipt_path=args.receipt,
        )
        print(render_receipt(receipt))
        return EXIT_OK if receipt.passed else EXIT_REFUSED

    if args.campaign_id is None:
        print(
            "Error: --campaign-id is required for run, rehearse, resume, "
            "status and report.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.command == "rehearse":
        # Imported inside the branch for the same reason `run` is: the
        # rehearsal seals an episode against a compiled graph, so it
        # reaches `build_workflow` and the read-only verbs must not.
        from src.campaign.rehearse import rehearse_campaign

        rehearsal = rehearse_campaign(
            config,
            root=root,
            campaign_id=args.campaign_id,
            approval_backend=_backend(args),
            approval_id=args.approval_id,
        )
        _emit(rehearsal.model_dump(mode="json"))
        return EXIT_OK

    if args.command == "report":
        # Imported here for the same reason `run` is: the report reads
        # episode records, and `src.campaign.execute` is where their
        # schema lives, so importing it at module scope would put the
        # graph's module graph behind the four read-only verbs.
        from src.campaign.report import build_report, render_report

        rendered = render_report(
            build_report(root, args.campaign_id, sink_root=args.sink_root)
        )
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(str(args.output))
        return EXIT_OK

    if args.command == "run":
        # Imported here, not at module import: `run` is the only verb
        # that touches the graph, and the four read-only verbs must not
        # pay for — or be able to reach — `build_workflow`.
        from src.campaign.execute import EpisodeStatePolicy, run_campaign

        report = run_campaign(
            config,
            root=root,
            campaign_id=args.campaign_id,
            approval_backend=_backend(args),
            sink_root=args.sink_root,
            max_episodes=args.max_episodes,
            scorer=_scorer(args, config, root),
            state_policy=EpisodeStatePolicy(
                retain_reader_chunks=not args.no_state_chunks
            ),
        )
        _emit(
            {
                "campaign_id": report.campaign_id,
                "directory": report.directory,
                "attempted": report.attempted,
                "completed": report.completed,
                "skipped_already_complete": report.skipped_already_complete,
                "pending_after": report.pending_after,
                "stop_reason": report.stop_reason,
                "stop_detail": report.stop_detail,
                "campaign_cost_usd_max": report.campaign_cost_usd_max,
                "observed_cost_usd": report.observed_cost_usd,
                "model_calls": report.model_calls,
                "judge_model_calls": report.judge_model_calls,
                "elapsed_seconds": round(report.elapsed_seconds, 3),
                "counts": dict(report.counts),
                "analysis_denominator": report.summary.denominators.analysis_denominator,
            }
        )
        return EXIT_OK

    if args.command == "resume":
        plan, pending = resume_campaign(root, campaign_id=args.campaign_id)
        _emit(
            {
                "campaign_id": plan.campaign_id,
                "lock_digest": plan.manifest.payload.lock_digest,
                "campaign_cost_usd_max": (
                    plan.manifest.payload.protocol.campaign_budget.total_cost_usd_max
                ),
                "pending": [
                    {
                        "design_index": episode.design_index,
                        "case_id": episode.case_id,
                        "arm_id": episode.arm_id,
                        "repeat_index": episode.repeat_index,
                        "run_id": episode.run_id,
                        "output_path": episode.output_path,
                    }
                    for episode in pending
                ],
            }
        )
        return EXIT_OK

    ledger = campaign_status(root, args.campaign_id)
    plan = rebuild_plan(*_loaded(root, args.campaign_id))
    _emit(
        {
            "campaign_id": ledger.campaign_id,
            "expected": ledger.report.expected,
            "analysis_denominator": ledger.report.analysis_denominator,
            "counts": status_counts(ledger),
            "corpus_mode": plan.manifest.payload.protocol.corpus_mode,
        }
    )
    return EXIT_OK


def _scorer(args: argparse.Namespace, config: Settings, root: Path) -> Any:
    """Resolve the `run` verb's scorer, or `None` for the free default.

    Three mutually exclusive answers and one refusal. `--mock-judge`
    executes the three rubrics against the checked-in fixture at zero
    cost (ADR 0095); `--live-judge` executes them against the provider
    under the *sealed* judge allocation — read from the campaign's own
    manifest rather than from a flag, because the cap an episode's judges
    may spend is part of the protocol an approval covered and is not an
    operator's to raise at the command line; neither leaves the free
    deterministic scorer, which `execute_campaign` refuses for a campaign
    that budgeted judge calls.

    Both at once is refused rather than resolved by precedence. They
    answer the same question with opposite methods, and a run that
    silently picked one would put a number in a campaign report whose
    provenance is a flag-ordering rule.
    """
    if args.mock_judge and args.live_judge:
        raise CampaignError(
            "--mock-judge and --live-judge both score the same three rubrics, "
            "one from a fixture and one from the provider; name one"
        )
    if args.mock_judge:
        from src.eval.mock_judge import build_mock_judge_scorer

        return build_mock_judge_scorer(config)
    if args.live_judge:
        from src.campaign.planner import load_campaign
        from src.campaign.scoring import build_live_judge_scorer

        manifest, _specs = load_campaign(root / args.campaign_id)
        return build_live_judge_scorer(
            config,
            judge_cost_usd_max=(
                manifest.payload.protocol.episode_budget.judge_cost_usd_max
            ),
        )
    return None


def _write_artifact(
    args: argparse.Namespace, plan: Any, request: CampaignRequest
) -> Path:
    """Publish the dry run's plan as an artifact a commit can hold.

    The `produced_by` line is rebuilt from the resolved request rather
    than from `sys.argv`, so the command recorded in the file is the one
    that reproduces it and not whatever else the operator typed.
    """
    from src.campaign.baseline import (
        artifact_command,
        build_plan_artifact,
        write_plan_artifact,
    )

    target: Path = args.artifact
    return write_plan_artifact(
        target,
        build_plan_artifact(
            plan,
            request=request,
            produced_by=artifact_command(request, output=str(target)),
            derived_from=str(args.registry_root),
        ),
    )


def _loaded(root: Path, campaign_id: str) -> Any:
    from src.campaign.planner import load_campaign

    return load_campaign(root / campaign_id)


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_USAGE", "main"]
