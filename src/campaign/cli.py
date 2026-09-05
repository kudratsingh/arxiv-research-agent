"""`python -m src.campaign plan|dry-run|resume|status`.

Four verbs, and the split between them is the work order's: **`plan` and
`dry-run` have no execution side effects.** `dry-run` writes nothing at
all and enumerates every planned episode with its zero-cost status;
`plan` materializes the campaign directory — manifest, lock, arm
configs, task set and the denominator ledger — and still runs nothing.
`resume` reopens a materialized campaign under the same lock and cap and
reports what is left; `status` reconciles the ledger against the receipts
on disk.

Nothing here compiles a graph or constructs a provider. Arm capability is
left `unverified` at plan time and proved at seal time by the process
that actually has a compiled graph, which is the only place the evidence
exists.

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
    write_campaign,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.registry import (
    BenchmarkSuite,
    IntendedUse,
    LocalRegistry,
    RegistryRole,
    TaskSet,
)

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
        "command", choices=("plan", "dry-run", "resume", "status")
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
            "Comma-separated arms. Default: all five. Arm E is always "
            "declared capability_missing and is never planned as runnable."
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
    parser.add_argument("--campaign-id", default=None, help="For resume and status.")
    return parser


def _config() -> Settings:
    """The shipped settings, with the campaign's own frozen values on top.

    `model_copy` rather than a fresh `Settings()`: the campaign inherits
    whatever the deployment configured and overrides only what the arm
    table owns, which is applied per arm by `arm_settings`.
    """
    patched = shipped_settings.model_copy(update={"enable_checkpointing": False})
    assert isinstance(patched, Settings)
    return patched


def _case_ids(root: Path, suite: str, explicit: str) -> tuple[str, ...]:
    """Read the suite's case order from the registry, or take the operator's."""
    if explicit.strip():
        return tuple(item.strip() for item in explicit.split(",") if item.strip())
    registry = LocalRegistry(root)
    ref = suite_ref(root, suite)
    envelope = registry.resolve(
        ref, role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT
    )
    payload = envelope.payload
    if not isinstance(payload, BenchmarkSuite):
        raise CampaignError(f"{suite} did not resolve to a benchmark suite")
    task_set = registry.resolve(
        payload.task_set_ref,
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    if not isinstance(task_set, TaskSet):
        raise CampaignError("suite task_set_ref did not resolve to a task set")
    return tuple(ref.id for ref in task_set.case_refs)


def _request(args: argparse.Namespace, config: Settings) -> CampaignRequest:
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
    args = _parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return _run(args)
    except CampaignError as exc:
        print(f"Refused: {exc.detail}", file=sys.stderr)
        return EXIT_REFUSED


def _run(args: argparse.Namespace) -> int:
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
            return EXIT_OK
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

    if args.campaign_id is None:
        print("Error: --campaign-id is required for resume and status.", file=sys.stderr)
        return EXIT_USAGE

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


def _loaded(root: Path, campaign_id: str) -> Any:
    from src.campaign.planner import load_campaign

    return load_campaign(root / campaign_id)


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_USAGE", "main"]
