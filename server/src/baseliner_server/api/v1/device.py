from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.api.deps import get_db, get_current_device
from baseliner_server.db.models import Device, Policy, PolicyAssignment
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.report import SubmitReportRequest, SubmitReportResponse
from baseliner_server.services.policy_compiler import compile_effective_policy
from baseliner_server.db.models import Run, RunItem, LogEvent

import uuid
from datetime import datetime, timezone

router = APIRouter(tags=["device"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        return EffectivePolicyResponse(mode="enforce", document={})

    assignment, policy = row
    return EffectivePolicyResponse(
        policy_id=str(policy.id),
        policy_name=policy.name,
        schema_version=policy.schema_version,
        mode=assignment.mode.value,
        document=policy.document,
    )


@router.post("/device/reports", response_model=SubmitReportResponse)
def submit_report(
    payload: SubmitReportRequest,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
) -> SubmitReportResponse:
    run = Run(
    device_id=device.id,
    started_at=payload.started_at,
    ended_at=payload.ended_at,
    status=payload.status,
    agent_version=payload.agent_version,
    effective_policy_hash=payload.effective_policy_hash,  # NEW
    policy_snapshot=payload.policy_snapshot or {},
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
            status_detect=item.status_detect,
            status_remediate=item.status_remediate,
            status_validate=item.status_validate,
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
