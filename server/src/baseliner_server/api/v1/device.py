from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.api.deps import get_current_device, get_db
from baseliner_server.core.policy_hash import compute_effective_policy_hash
from baseliner_server.db.models import Device, LogEvent, Policy, PolicyAssignment, Run, RunItem
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.report import SubmitReportRequest, SubmitReportResponse
from baseliner_server.db.models import StepStatus


router = APIRouter(tags=["device"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _coerce_step_status(value: str | None) -> StepStatus:
    """
    Accept legacy/agent strings and map to DB enum values.
    DB StepStatus allows: not_run, ok, fail, skipped
    """
    v = (value or "").strip().lower()
    if v in ("", "none"):
        return StepStatus.not_run
    if v == "failed":
        v = "fail"
    try:
        return StepStatus(v)  # type: ignore[arg-type]
    except Exception:
        return StepStatus.not_run

def normalize_policy_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize policy_snapshot keys so we don't store a mix of camelCase/snake_case.
    """
    if not snapshot:
        return {}

    keymap = {
        "policyId": "policy_id",
        "policyName": "policy_name",
        "schemaVersion": "schema_version",
        "effectivePolicyHash": "effective_policy_hash",
    }

    out: dict[str, Any] = {}
    for k, v in snapshot.items():
        out[keymap.get(k, k)] = v
    return out


@router.get("/device/policy", response_model=EffectivePolicyResponse)
def get_effective_policy(
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
) -> EffectivePolicyResponse:
    # MVP: choose highest priority active policy assignment (lowest priority number wins)
    stmt = (
        select(PolicyAssignment, Policy)
        .join(Policy, Policy.id == PolicyAssignment.policy_id)
        .where(PolicyAssignment.device_id == device.id)
        .where(Policy.is_active == True)  # noqa: E712
        .order_by(PolicyAssignment.priority.asc())
        .limit(1)
    )
    row = db.execute(stmt).first()

    if not row:
        resp = EffectivePolicyResponse(mode="enforce", document={}, sources=[])
        resp.effective_policy_hash = compute_effective_policy_hash(
            policy_id=resp.policy_id,
            policy_name=resp.policy_name,
            schema_version=resp.schema_version,
            mode=resp.mode,
            document=resp.document,
            sources=resp.sources,
        )
        return resp

    assignment, policy = row

    # Optional provenance (helps explain "why did I get this policy?")
    sources = [
        {
            "type": "device_assignment",
            "device_id": str(device.id),
            "policy_id": str(policy.id),
            "priority": assignment.priority,
            "mode": assignment.mode.value,
        }
    ]

    resp = EffectivePolicyResponse(
        policy_id=str(policy.id),
        policy_name=policy.name,
        schema_version=policy.schema_version,
        mode=assignment.mode.value,
        document=policy.document,
        sources=sources,
    )

    # Server-side effective hash (so agents can skip if unchanged)
    resp.effective_policy_hash = compute_effective_policy_hash(
        policy_id=resp.policy_id,
        policy_name=resp.policy_name,
        schema_version=resp.schema_version,
        mode=resp.mode,
        document=resp.document,
        sources=resp.sources,
    )

    return resp


@router.post("/device/reports", response_model=SubmitReportResponse)
def submit_report(
    payload: SubmitReportRequest,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
) -> SubmitReportResponse:
    snapshot = normalize_policy_snapshot(payload.policy_snapshot or {})

    run = Run(
        device_id=device.id,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        status=payload.status,
        agent_version=payload.agent_version,
        effective_policy_hash=payload.effective_policy_hash,  # agent sends server hash (or fallback)
        policy_snapshot=snapshot,
        summary=payload.summary or {},
    )
    db.add(run)
    db.flush()  # run.id available

    # Items (we store ordinal so logs can reference it)
    ordinal_to_item_id: dict[int, uuid.UUID] = {}
    for item in payload.items:
        run_item = RunItem(
            run_id=run.id,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            name=item.name,
            ordinal=item.ordinal,
            compliant_before=item.compliant_before,
            compliant_after=item.compliant_after,
            changed=item.changed,
            reboot_required=item.reboot_required,
            status_detect=_coerce_step_status(item.status_detect),
            status_remediate=_coerce_step_status(item.status_remediate),
            status_validate=_coerce_step_status(item.status_validate),
            started_at=item.started_at,
            ended_at=item.ended_at,
            evidence=item.evidence or {},
            error=item.error or {},
        )
        db.add(run_item)
        db.flush()
        ordinal_to_item_id[item.ordinal] = run_item.id

    # Logs
    for log in payload.logs:
        run_item_id = None
        if log.run_item_ordinal is not None:
            run_item_id = ordinal_to_item_id.get(log.run_item_ordinal)

        db.add(
            LogEvent(
                run_id=run.id,
                run_item_id=run_item_id,
                ts=log.ts or utcnow(),
                level=log.level,
                message=log.message,
                data=log.data or {},
            )
        )

    db.commit()
    return SubmitReportResponse(run_id=str(run.id))
