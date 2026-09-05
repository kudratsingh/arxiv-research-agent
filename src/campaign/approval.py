"""Approval admission for a campaign, with a local record backend for tests.

RFC 09 §10.2 and work-order invariant 10 say the same thing from two
directions: *possessing an API key or declaring a positive ceiling never
authorizes chargeable work*, and a chargeable plan is rejected **before
credentials are read**. This module is what makes both testable without
inventing an approval authority.

Three rules it keeps:

- **The record is external.** `ApprovalRecord` is W03's model and this
  package only *reads* records — from a file an operator wrote, or from
  a list a test constructed. Nothing here mints an approval for the
  campaign it is admitting; `campaign_approval_record` is a builder for
  a record whose authority comes from elsewhere, and it is used by tests
  and by an operator preparing a record, never by the planner.
- **Verification precedes credentials.** `resolve_admission` calls the
  backend first and the credential probe second, and
  `SettingsCredentialProbe` is the only thing in this package that looks
  at a key. A plan with no approval never reaches it.
- **The scope has to cover the plan.** Campaign, stage, provider,
  resources and all four caps are checked; a stage-1 approval does not
  authorize stage 2, and a $5 approval does not authorize a $50 campaign.
  That logic is W03's `FakeLocalApprovalBackend` and is delegated to
  rather than reimplemented, so the two cannot drift.

A live campaign still needs the owner's D9 approval, recorded outside
this repository. Nothing in this file changes that, and P0-WO12 remains
blocked whatever a local record file says.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.campaign.errors import CampaignError
from src.config import Settings
from src.contracts.kernel import MoneyUsd, Rfc3339Utc, sha256_digest
from src.contracts.run_manifest import (
    ApprovalRecord,
    ApprovalScope,
    ApprovalStatus,
    ApprovalVerificationReceipt,
    CampaignId,
    FakeLocalApprovalBackend,
    RunManifestError,
)

#: The key the repository uses everywhere to mean "no paid call may
#: succeed". It is truthy, so a presence check passes and a *spend* check
#: is the thing that has to fail — which is exactly the property this
#: module tests: possession is not authorization.
DISABLED_API_KEY: Final[str] = "local-preview-disabled"


class LocalApprovalRecordBackend:
    """Read-only approval backend over records this process was handed.

    Satisfies W03's `ApprovalBackend` protocol by delegating every check
    to `FakeLocalApprovalBackend`, and adds only what a campaign needs:
    loading records from a file an operator controls, and counting
    verifications so a test can prove one happened before a credential
    was read.
    """

    def __init__(self, records: Iterable[ApprovalRecord] = ()) -> None:
        self._records = tuple(records)
        self._delegate = FakeLocalApprovalBackend(self._records)

    @classmethod
    def from_file(cls, path: Path) -> LocalApprovalRecordBackend:
        """Load approval records from a JSON array outside this package.

        Args:
            path: File holding a JSON list of `ApprovalRecord` objects.

        Returns:
            A backend over exactly those records.

        Raises:
            CampaignError: The file is missing, unparseable, or holds
                something that is not a list of approval records. A
                malformed approval file admits nothing; it fails closed.
        """
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            raise CampaignError(f"approval record file is unreadable: {exc}") from exc
        if not isinstance(payload, list):
            raise CampaignError("approval record file must hold a JSON list")
        try:
            # Validated from JSON rather than from the parsed dicts: the
            # contract models are strict, so a list is not a tuple and
            # "approved" is not an `ApprovalStatus` until JSON mode says so.
            records = TypeAdapter(tuple[ApprovalRecord, ...]).validate_json(text)
        except ValueError as exc:
            raise CampaignError(f"approval record file is invalid: {exc}") from exc
        return cls(records)

    @property
    def calls(self) -> int:
        """How many verifications this backend has performed."""
        return int(self._delegate.calls)

    @property
    def record_ids(self) -> tuple[str, ...]:
        """The approval ids this backend can verify, for `status` output."""
        return tuple(record.approval_id for record in self._records)

    def verify(
        self,
        approval_id: str,
        *,
        campaign_id: str,
        stage: str,
        provider: str,
        resources: tuple[str, ...],
        required_total_usd: MoneyUsd,
        required_episode_usd: MoneyUsd,
        required_workflow_usd: MoneyUsd,
        required_judge_usd: MoneyUsd,
        verified_at: Rfc3339Utc,
    ) -> tuple[ApprovalRecord, ApprovalVerificationReceipt]:
        """Verify one approval against the plan it is being asked to cover."""
        return self._delegate.verify(
            approval_id,
            campaign_id=campaign_id,
            stage=stage,
            provider=provider,
            resources=resources,
            required_total_usd=required_total_usd,
            required_episode_usd=required_episode_usd,
            required_workflow_usd=required_workflow_usd,
            required_judge_usd=required_judge_usd,
            verified_at=verified_at,
        )


class SettingsCredentialProbe:
    """Look for a usable credential — and only after approval succeeded.

    Handed to `resolve_admission` as its `credential_probe`, which the
    admission controller calls *after* the approval backend returns. That
    ordering is the contract: a campaign with no approval record raises
    before this object is ever consulted, so "rejected before credential
    lookup" is a property of the call graph rather than of a comment.

    The probe refuses the repository's disabled placeholder explicitly.
    A truthy key that cannot pay is exactly the shape of the mistake
    invariant 10 is about, and letting it pass here would make a
    zero-spend checkout look like an authorized one.
    """

    def __init__(self, config: Settings) -> None:
        self._config = config
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        secret = self._config.anthropic_api_key
        key = secret.get_secret_value() if secret is not None else ""
        if not key:
            raise CampaignError("approved campaign has no provider credential configured")
        if key == DISABLED_API_KEY:
            raise CampaignError(
                "the disabled placeholder credential cannot run an approved "
                "campaign; a key that cannot pay is not authorization to spend"
            )


class NoCredentialProbe:
    """The probe a zero-cost campaign uses: it must never be called.

    A no-cost plan is not chargeable, `resolve_admission` skips the probe
    entirely, and this object raises if that ever stops being true. It is
    cheaper than a comment and it fails the test rather than the campaign.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        raise CampaignError("a zero-cost campaign must not read a credential")


def campaign_approval_record(
    *,
    approval_id: str,
    campaign_id: CampaignId,
    stage: str,
    provider: str,
    total_cost_usd_max: MoneyUsd,
    episode_allocation_usd_max: MoneyUsd,
    workflow_allocation_usd_max: MoneyUsd,
    judge_allocation_usd_max: MoneyUsd,
    approved_by: str,
    approved_at: Rfc3339Utc,
    expires_at: Rfc3339Utc,
    resources: Sequence[str] = (),
    status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> ApprovalRecord:
    """Build an approval record from an authority that already decided.

    This is a *shape* helper, not an approval. It exists so a test and an
    operator write the same object, and so the record digest is computed
    the same way in both. Calling it does not authorize anything: the
    record still has to be handed to a backend, and a campaign still has
    to name its id.

    Args:
        approval_id: Opaque id, `approval_<slug>`.
        campaign_id: The one campaign this record covers.
        stage: The one stage it covers.
        provider: The provider it covers.
        total_cost_usd_max: Aggregate cap.
        episode_allocation_usd_max: Per-episode cap.
        workflow_allocation_usd_max: Workflow share of an episode.
        judge_allocation_usd_max: Judge share of an episode.
        approved_by: Approver alias. Never a name plus a conversation.
        approved_at: When.
        expires_at: Until when.
        resources: Named resources beyond the provider.
        status: Defaults to approved; pass another to build the pending,
            expired or revoked records admission must reject.

    Returns:
        The record.

    Raises:
        CampaignError: The caps are not internally consistent.
    """
    try:
        scope = ApprovalScope(
            campaign_id=campaign_id,
            providers=(provider,),
            stages=(stage,),
            resources=tuple(resources),
            total_cost_usd_max=total_cost_usd_max,
            episode_allocation_usd_max=episode_allocation_usd_max,
            workflow_allocation_usd_max=workflow_allocation_usd_max,
            judge_allocation_usd_max=judge_allocation_usd_max,
        )
    except ValueError as exc:
        raise CampaignError(f"approval scope is not internally consistent: {exc}") from exc
    material = {
        "approval_id": approval_id,
        "scope": scope,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "expires_at": expires_at,
        "status": status.value,
    }
    try:
        return ApprovalRecord(
            approval_id=approval_id,
            status=status,
            scope=scope,
            approved_by=approved_by,
            approved_at=approved_at,
            expires_at=expires_at,
            record_digest=sha256_digest(material),
        )
    except ValueError as exc:
        raise CampaignError(f"approval record is invalid: {exc}") from exc


def assert_approval_covers(
    backend: LocalApprovalRecordBackend,
    *,
    approval_id: str | None,
    campaign_id: CampaignId,
    stage: str,
    provider: str,
    resources: Sequence[str],
    total_cost_usd_max: MoneyUsd,
    episode_total_usd_max: MoneyUsd,
    workflow_usd_max: MoneyUsd,
    judge_usd_max: MoneyUsd,
    verified_at: Rfc3339Utc,
) -> ApprovalVerificationReceipt | None:
    """Check the campaign-level approval before a single episode is sealed.

    Episode admission re-verifies per episode — RFC 09 §10.2 requires a
    fresh receipt at every seal and every resume — but a 300-episode
    campaign should not discover on episode one that its approval covers
    nothing. This is that pre-flight, and it uses the campaign's
    *aggregate* cap rather than an episode's.

    Args:
        backend: The approval backend.
        approval_id: The campaign's approval, or `None` for a zero-cost
            campaign.
        campaign_id: The campaign being admitted.
        stage: The stage being admitted.
        provider: The provider that would be charged.
        resources: Named resources the plan would use.
        total_cost_usd_max: The campaign's aggregate cap.
        episode_total_usd_max: The per-episode cap.
        workflow_usd_max: The workflow share of an episode.
        judge_usd_max: The judge share of an episode.
        verified_at: Verification time.

    Returns:
        The verification receipt, or `None` when the campaign is
        zero-cost and needs no approval.

    Raises:
        CampaignError: A chargeable campaign has no approval, or the
            approval does not cover it.
    """
    chargeable = Decimal(total_cost_usd_max) > 0
    if not chargeable:
        if approval_id is not None:
            raise CampaignError("a zero-cost campaign cannot claim approval backing")
        return None
    if approval_id is None:
        raise CampaignError(
            "a chargeable campaign requires an external approval record; a "
            "declared ceiling and a configured API key are not approval"
        )
    try:
        _, receipt = backend.verify(
            approval_id,
            campaign_id=campaign_id,
            stage=stage,
            provider=provider,
            resources=tuple(resources),
            required_total_usd=total_cost_usd_max,
            required_episode_usd=episode_total_usd_max,
            required_workflow_usd=workflow_usd_max,
            required_judge_usd=judge_usd_max,
            verified_at=verified_at,
        )
    except RunManifestError as exc:
        raise CampaignError(f"campaign approval does not cover this plan: {exc.detail}") from exc
    return receipt


__all__ = [
    "DISABLED_API_KEY",
    "LocalApprovalRecordBackend",
    "NoCredentialProbe",
    "SettingsCredentialProbe",
    "assert_approval_covers",
    "campaign_approval_record",
]
