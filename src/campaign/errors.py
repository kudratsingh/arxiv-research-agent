"""The one failure this package raises.

A campaign either resolves, plans, seals and reconciles — or it refuses
and says which structural fact stopped it. There is no degraded
campaign, no partially-locked registry and no manifest written "anyway",
so one coded error with a human-readable detail is the whole vocabulary.

The code is reused from the shared kernel rather than invented here:
callers that already switch on `ContractErrorCode` keep working, and a
campaign refusal is never a new *class* of failure — it is a schema,
digest, reference or version failure at a larger scale.
"""

from __future__ import annotations

from src.contracts.kernel import ContractError, ContractErrorCode


class CampaignError(ContractError):
    """A campaign cannot be expressed, planned, sealed or resumed.

    Always a refusal, never a repair. Every raiser in this package names
    the fact that stopped it — a changed lock, a raised cap, a graph that
    does not earn the arm it claims, an approval that does not cover the
    plan — because the operator's next action differs for each and a
    generic "campaign failed" would hide it.
    """

    def __init__(
        self,
        detail: str,
        *,
        code: ContractErrorCode = ContractErrorCode.SCHEMA_INVALID,
    ) -> None:
        super().__init__(code, detail)


__all__ = ["CampaignError"]
