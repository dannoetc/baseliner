from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

# NOTE: dependencies live in api.deps; core.auth only contains the auth logic.
from baseliner_server.api.deps import get_current_device, get_db
from baseliner_server.core.policy_hash import compute_effective_policy_hash
from baseliner_server.services.policy_compiler import compile_effective_policy
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
    """Return the *effective* policy for this device.

    Devices can have multiple policy assignments. We compile them into a single
    document by priority (lowest number first), with 'first-wins' semantics on
    (type,id) for resources.
    """
    snap = compile_effective_policy(db, device)
    resp = EffectivePolicyResponse(
        policy_id=None,
        policy_name=None,
        schema_version='1',
        mode=snap.mode,
        document=snap.policy,
        effective_policy_hash=str(snap.meta.get('effective_hash') or ''),
        sources=snap.meta.get('sources') or [],
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
