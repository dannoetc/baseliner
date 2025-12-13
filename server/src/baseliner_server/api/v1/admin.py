import secrets
from datetime import datetime, timezone

from fastapi import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query

from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.db.models import RunItem, LogEvent
from baseliner_server.schemas.run_detail import RunDetailResponse, RunItemDetail, LogEventDetail

from baseliner_server.db.models import Run
from baseliner_server.schemas.admin_list import DevicesListResponse, RunsListResponse, DeviceSummary, RunSummary
from baseliner_server.schemas.policy_admin import UpsertPolicyRequest, UpsertPolicyResponse
from baseliner_server.api.deps import get_db, hash_token, require_admin
from baseliner_server.db.models import Device, EnrollToken, Policy, PolicyAssignment, AssignmentMode
from baseliner_server.schemas.admin import (
    AssignPolicyRequest,
    AssignPolicyResponse,
    CreateEnrollTokenRequest,
    CreateEnrollTokenResponse,
)

router = APIRouter(tags=["admin"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/admin/enroll-tokens", response_model=CreateEnrollTokenResponse, dependencies=[Depends(require_admin)])
def create_enroll_token(payload: CreateEnrollTokenRequest, db: Session = Depends(get_db)) -> CreateEnrollTokenResponse:
    raw = secrets.token_urlsafe(24)
    tok = EnrollToken(
        token_hash=hash_token(raw),
        created_at=utcnow(),
        expires_at=payload.expires_at,
        used_at=None,
        note=payload.note,
    )
    db.add(tok)
    db.commit()
    return CreateEnrollTokenResponse(enroll_token=raw, expires_at=payload.expires_at)


@router.post("/admin/assign-policy", response_model=AssignPolicyResponse, dependencies=[Depends(require_admin)])
def assign_policy(payload: AssignPolicyRequest, db: Session = Depends(get_db)) -> AssignPolicyResponse:
    device = db.scalar(select(Device).where(Device.id == payload.device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    policy = db.scalar(select(Policy).where(Policy.name == payload.policy_name))
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    mode = AssignmentMode.enforce if payload.mode.lower() == "enforce" else AssignmentMode.audit

    existing = db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.device_id == device.id, PolicyAssignment.policy_id == policy.id
        )
    )
    if existing:
        existing.mode = mode
        existing.priority = payload.priority
        db.add(existing)
    else:
        db.add(
            PolicyAssignment(
                device_id=device.id,
                policy_id=policy.id,
                mode=mode,
                priority=payload.priority,
            )
        )


    db.commit()
    return AssignPolicyResponse(ok=True)

@router.post("/admin/policies", response_model=UpsertPolicyResponse, dependencies=[Depends(require_admin)])
def upsert_policy(payload: UpsertPolicyRequest, db: Session = Depends(get_db)) -> UpsertPolicyResponse:
    existing = db.scalar(select(Policy).where(Policy.name == payload.name))

    if existing:
        existing.description = payload.description
        existing.schema_version = payload.schema_version
        existing.document = payload.document
        existing.is_active = payload.is_active
        existing.updated_at = utcnow()
        db.add(existing)
        db.commit()
        return UpsertPolicyResponse(policy_id=str(existing.id), name=existing.name, is_active=existing.is_active)

    policy = Policy(
        name=payload.name,
        description=payload.description,
        schema_version=payload.schema_version,
        document=payload.document,
        is_active=payload.is_active,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(policy)
    db.commit()
    return UpsertPolicyResponse(policy_id=str(policy.id), name=policy.name, is_active=policy.is_active)
@router.get("/admin/devices", response_model=DevicesListResponse, dependencies=[Depends(require_admin)])
def list_devices(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> DevicesListResponse:
    stmt = (
        select(Device)
        .order_by(desc(Device.last_seen_at), desc(Device.enrolled_at))
        .offset(offset)
        .limit(limit)
    )
    devices = list(db.scalars(stmt).all())

    return DevicesListResponse(
        items=[
            DeviceSummary(
                id=str(d.id),
                device_key=d.device_key,
                hostname=d.hostname,
                os=d.os,
                os_version=d.os_version,
                arch=d.arch,
                agent_version=d.agent_version,
                enrolled_at=d.enrolled_at,
                last_seen_at=d.last_seen_at,
                tags=d.tags or {},
            )
            for d in devices
        ],
        limit=limit,
        offset=offset,
    )


@router.get("/admin/runs", response_model=RunsListResponse, dependencies=[Depends(require_admin)])
def list_runs(
    db: Session = Depends(get_db),
    device_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RunsListResponse:
    stmt = select(Run).order_by(desc(Run.started_at)).offset(offset).limit(limit)

    if device_id:
        stmt = stmt.where(Run.device_id == device_id)

    runs = list(db.scalars(stmt).all())

    return RunsListResponse(
        items=[
            RunSummary(
                id=str(r.id),
                device_id=str(r.device_id),
                started_at=r.started_at,
                ended_at=r.ended_at,
                status=r.status.value if hasattr(r.status, "value") else str(r.status),
                agent_version=r.agent_version,
                summary=r.summary or {},
                policy_snapshot=r.policy_snapshot or {},
            )
            for r in runs
        ],
        limit=limit,
        offset=offset,
    )

@router.get("/admin/runs/{run_id}", response_model=RunDetailResponse, dependencies=[Depends(require_admin)])
def get_run_detail(
    run_id: str = Path(...),
    db: Session = Depends(get_db),
) -> RunDetailResponse:
    run = db.scalar(select(Run).where(Run.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = list(db.scalars(select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.ordinal.asc())).all())
    logs = list(db.scalars(select(LogEvent).where(LogEvent.run_id == run.id).order_by(LogEvent.ts.asc())).all())

    def _status(v) -> str:
        return v.value if hasattr(v, "value") else str(v)

    return RunDetailResponse(
        id=str(run.id),
        device_id=str(run.device_id),
        started_at=run.started_at,
        ended_at=run.ended_at,
        status=_status(run.status),
        agent_version=run.agent_version,
        summary=run.summary or {},
        policy_snapshot=run.policy_snapshot or {},
        items=[
            RunItemDetail(
                id=str(i.id),
                ordinal=i.ordinal,
                resource_type=i.resource_type,
                resource_id=i.resource_id,
                name=i.name,
                compliant_before=i.compliant_before,
                compliant_after=i.compliant_after,
                changed=i.changed,
                reboot_required=i.reboot_required,
                status_detect=_status(i.status_detect),
                status_remediate=_status(i.status_remediate),
                status_validate=_status(i.status_validate),
                started_at=i.started_at,
                ended_at=i.ended_at,
                evidence=i.evidence or {},
                error=i.error or {},
            )
            for i in items
        ],
        logs=[
            LogEventDetail(
                id=str(l.id),
                ts=l.ts,
                level=_status(l.level),
                message=l.message,
                data=l.data or {},
                run_item_id=str(l.run_item_id) if l.run_item_id else None,
            )
            for l in logs
        ],
    )
