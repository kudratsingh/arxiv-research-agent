"""Four named count-only requests, with no approval writer or Messages path.

Reuse the durable job/contact journal and source/credential fences. A count job
has a zero-dollar reservation: lost contact is still uncertain and unreplayable,
but it never invents workflow/checker spending. The count is a provider estimate,
not billed usage. MockTransport integers remain explicitly synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.workspace.admission import AdmissionError, GenerationAdmission, _digest
from src.workspace.provider_adapter import QualificationAdapter


class MeasurementAdmission(GenerationAdmission):
    @staticmethod
    def _valid_amount(amount: Decimal) -> bool:
        return amount == 0

    @staticmethod
    def _request_id(policy: dict[str, Any], request_id: str, inputs: dict[str, Any]) -> None:
        if not any(
            entry["request_id"] == request_id and entry["input_digest"] == _digest(inputs)
            for entry in policy["count_requests"]
        ):
            raise AdmissionError("approved_count_request_id_required")

    @staticmethod
    def _policy(
        conn: Any, owner: str, inputs: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any]]:
        approval, policy = GenerationAdmission._policy(conn, owner, inputs, now)
        entries = policy.get("count_requests")
        if (
            policy.get("purpose") != "workspace-measurement-only"
            or policy.get("transport_mode") not in {"mock", "provider"}
            or policy.get("everyday_generation") is not False
            or policy.get("messages_contacts_max") != 0
            or policy.get("count_contacts_max") != 4
            or not isinstance(entries, list)
            or len(entries) != 4
            or any(
                not isinstance(e, dict)
                or set(e) != {"request_id", "input_digest", "count_request_digest"}
                or any(not isinstance(v, str) or not v.strip() for v in e.values())
                for e in entries
            )
            or any(len({e[k] for e in entries}) != 4 for k in entries[0])
            or _digest(inputs) not in {e["input_digest"] for e in entries}
        ):
            raise AdmissionError("measurement_only_approval_required")
        return approval, policy


class MeasurementAdapter(QualificationAdapter):
    admission_type: type[GenerationAdmission] = MeasurementAdmission
    allowed_endpoints = frozenset({"messages/count_tokens"})

    def start(
        self, request_id: str, amount_usd: str = "0", *, now: datetime | None = None
    ) -> dict[str, Any]:
        if amount_usd != "0":
            raise AdmissionError("measurement_reservation_must_be_zero")
        return self._start(request_id, "0", now=now)

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        job_id: str | None = None,
        ordinal: int | None = None,
    ) -> dict[str, Any]:
        if path not in self.allowed_endpoints:
            raise AdmissionError("endpoint_not_permitted")
        with self.store.pool.connection() as conn:
            _, policy = self.control._policy(
                conn, self.owner, self.inputs.snapshot(), datetime.now().astimezone()
            )
        if not any(
            e["input_digest"] == _digest(self.inputs.snapshot())
            and e["count_request_digest"] == _digest(body)
            for e in policy["count_requests"]
        ):
            raise AdmissionError("approved_count_body_required")
        return await super()._post(path, body, job_id=job_id, ordinal=ordinal)

    async def advance(
        self, job_id: str, *, cancelled: Callable[[], bool] = lambda: False
    ) -> dict[str, Any]:
        if cancelled():
            return self.control.cancel(self.owner, job_id)
        try:
            wire = self.request(job_id)
            ordinal = self._contact(job_id, wire, "messages/count_tokens")
            body = {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
            response = await self._post(
                "messages/count_tokens", body, job_id=job_id, ordinal=ordinal
            )
            self._record(job_id, ordinal, response)
            if self.snapshot(job_id)["state"] != "running":
                return self.snapshot(job_id)
            tokens = response.get("input_tokens")
            if type(tokens) is not int or tokens < 0:
                raise AdmissionError("invalid_count_response")
            if cancelled():
                return self.control.cancel(self.owner, job_id)
            self.control.reconcile(
                self.owner,
                job_id,
                receipt_id="count-only",
                workflow_usd="0",
                judge_usd="0",
                final=True,
                result={
                    "measurement_only": True,
                    "input_tokens": tokens,
                    "basis": "synthetic MockTransport integer; unmeasured"
                    if self.mode == "mock"
                    else "provider count estimate; not billed usage",
                    "count_request_digest": _digest(body),
                    "everyday_generation": False,
                },
            )
            return self.snapshot(job_id)
        except BaseException:
            self.control.recover(self.owner, job_id)
            raise
