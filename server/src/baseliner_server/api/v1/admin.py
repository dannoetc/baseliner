import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from baseliner_server.services.policy_compiler import compile_effective_policy

from baseliner_server.api.deps import get_db, hash_token, require_admin
from baseliner_server.db.models import (
    AssignmentMode,
    Device,
    EnrollToken,
    LogEvent,
    Policy,
    PolicyAssignment,
    Run,
    RunItem,
)
from baseliner_server.schemas.admin import (
    AssignPolicyRequest,
    AssignPolicyResponse,
    CreateEnrollTokenRequest,
    CreateEnrollTokenResponse,
    DeviceAssignmentsResponse,
    ClearAssignmentsResponse,
    PolicyAssignmentOut,
    DeviceDebugResponse,
    PolicyAssignmentDebugOut,
    RunDebugSummary,
)
from baseliner_server.schemas.admin_list import (
    DeviceSummary,
    DevicesListResponse,
    RunSummary,
    RunsListResponse,
)
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.policy_admin import UpsertPolicyRequest, UpsertPolicyResponse
from baseliner_server.schemas.run_detail import RunDetailResponse, RunItemDetail, LogEventDetail

router = APIRouter(tags=["admin"])


def utcnow() -> datetime:
    # Return a timezone-naive UTC datetime.
    # (SQLite + tests are using naive datetimes, so keep it consistent.)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _status(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v.value if hasattr(v, "value") else str(v)


@router.post(
    "/admin/enroll-tokens",
    response_model=CreateEnrollTokenResponse,
    dependencies=[Depends(require_admin)],
)
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


@router.post(
    "/admin/assign-policy",
    response_model=AssignPolicyResponse,
    dependencies=[Depends(require_admin)],
)
def assign_policy(payload: AssignPolicyRequest, db: Session = Depends(get_db)) -> AssignPolicyResponse:
    device = db.scalar(select(Device).where(Device.id == payload.device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    policy = db.scalar(select(Policy).where(Policy.name == payload.policy_name))
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    mode = AssignmentMode.enforce if (payload.mode or "").lower() == "enforce" else AssignmentMode.audit

    existing = db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.device_id == device.id,
            PolicyAssignment.policy_id == policy.id,
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


@router.get(
    "/admin/devices/{device_id}/assignments",
    response_model=DeviceAssignmentsResponse,
    dependencies=[Depends(require_admin)],
)
def list_device_assignments(
    device_id: str = Path(..., description="Device UUID"),
    db: Session = Depends(get_db),
) -> DeviceAssignmentsResponse:
    """Return the current policy assignments for a device (admin/debug helper)."""

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Keep ordering consistent with the policy compiler:
    # priority asc (lower wins), then created_at asc, then assignment id asc.
    rows = (
        db.query(PolicyAssignment, Policy)
        .join(Policy, Policy.id == PolicyAssignment.policy_id)
        .filter(PolicyAssignment.device_id == device.id)
        .order_by(
            PolicyAssignment.priority.asc(),
            PolicyAssignment.created_at.asc(),
            PolicyAssignment.id.asc(),
        )
        .all()
    )

    out: list[PolicyAssignmentOut] = []
    for a, pol in rows:
        out.append(
            PolicyAssignmentOut(
                policy_id=str(a.policy_id),
                policy_name=pol.name,
                priority=int(a.priority),
                mode=_status(a.mode) or "enforce",
                is_active=bool(pol.is_active),
            )
        )

    return DeviceAssignmentsResponse(device_id=device_id, assignments=out)


@router.delete(
    "/admin/devices/{device_id}/assignments",
    response_model=ClearAssignmentsResponse,
    dependencies=[Depends(require_admin)],
)
def clear_device_assignments(
    device_id: str = Path(..., description="Device UUID"),
    db: Session = Depends(get_db),
) -> ClearAssignmentsResponse:
    """Remove all policy assignments for a device (admin/debug helper)."""

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    removed = (
        db.query(PolicyAssignment)
        .filter(PolicyAssignment.device_id == device.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return ClearAssignmentsResponse(device_id=device_id, removed=int(removed or 0))


@router.get(
    "/admin/devices/{device_id}/debug",
    response_model=DeviceDebugResponse,
    dependencies=[Depends(require_admin)],
)
def debug_device_bundle(
    device_id: str = Path(..., description="Device UUID"),
    db: Session = Depends(get_db),
) -> DeviceDebugResponse:
    """First-class "debug this device" bundle for operator workflow.

    Returns:
      - device summary
      - ordered assignments
      - compiled effective policy (+ compile metadata)
      - last run summary + items
    """

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Assignments (ordered exactly like the compiler)
    rows = (
        db.query(PolicyAssignment, Policy)
        .join(Policy, Policy.id == PolicyAssignment.policy_id)
        .filter(PolicyAssignment.device_id == device.id)
        .order_by(
            PolicyAssignment.priority.asc(),
            PolicyAssignment.created_at.asc(),
            PolicyAssignment.id.asc(),
        )
        .all()
    )

    assignments_out: list[PolicyAssignmentDebugOut] = []
    for a, pol in rows:
        assignments_out.append(
            PolicyAssignmentDebugOut(
                assignment_id=str(a.id),
                created_at=a.created_at,
                policy_id=str(a.policy_id),
                policy_name=pol.name,
                priority=int(a.priority),
                mode=_status(a.mode) or "enforce",
                is_active=bool(pol.is_active),
            )
        )

    # Effective policy (compiled)
    snap = compile_effective_policy(db, device)
    effective_policy = EffectivePolicyResponse(
        policy_id=None,
        policy_name=None,
        schema_version="1",
        mode=snap.mode,
        document=snap.policy,
        effective_policy_hash=str(snap.meta.get("effective_hash") or ""),
        sources=snap.meta.get("sources") or [],
        compile=snap.meta.get("compile") or {},
    )

    # Last run (summary + items)
    last_run = db.scalar(
        select(Run)
        .where(Run.device_id == device.id)
        .order_by(desc(Run.started_at), desc(Run.id))
        .limit(1)
    )

    last_run_summary: RunDebugSummary | None = None
    last_items_out: list[RunItemDetail] = []
    if last_run:
        last_run_summary = RunDebugSummary(
            id=str(last_run.id),
            started_at=last_run.started_at,
            ended_at=last_run.ended_at,
            status=_status(last_run.status),
            agent_version=last_run.agent_version,
            effective_policy_hash=last_run.effective_policy_hash,
            summary=last_run.summary or {},
            policy_snapshot=last_run.policy_snapshot or {},
            detail_path=f"/api/v1/admin/runs/{last_run.id}",
        )

        items = list(
            db.scalars(
                select(RunItem)
                .where(RunItem.run_id == last_run.id)
                .order_by(RunItem.ordinal.asc())
            ).all()
        )

        last_items_out = [
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
                status_detect=_status(i.status_detect) or "unknown",
                status_remediate=_status(i.status_remediate) or "unknown",
                status_validate=_status(i.status_validate) or "unknown",
                started_at=i.started_at,
                ended_at=i.ended_at,
                evidence=i.evidence or {},
                error=i.error or {},
            )
            for i in items
        ]

    device_summary = DeviceSummary(
        id=str(device.id),
        device_key=device.device_key,
        hostname=device.hostname,
        os=device.os,
        os_version=device.os_version,
        arch=device.arch,
        agent_version=device.agent_version,
        enrolled_at=device.enrolled_at,
        last_seen_at=device.last_seen_at,
        tags=device.tags or {},
    )

    return DeviceDebugResponse(
        device=device_summary,
        assignments=assignments_out,
        effective_policy=effective_policy,
        last_run=last_run_summary,
        last_run_items=last_items_out,
    )


@router.post(
    "/admin/policies",
    response_model=UpsertPolicyResponse,
    dependencies=[Depends(require_admin)],
)
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


@router.get(
    "/admin/devices",
    response_model=DevicesListResponse,
    dependencies=[Depends(require_admin)],
)
def list_devices(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_health: bool = Query(
        False,
        description="If true, include last_run + computed health fields per device.",
    ),
    stale_after_seconds: int = Query(
        1800,
        ge=60,
        le=60 * 60 * 24,
        description="Mark device as 'stale' if latest run is older than this many seconds.",
    ),
    offline_after_seconds: int = Query(
        3600,
        ge=60,
        le=60 * 60 * 24 * 7,
        description="Mark device as 'offline' if last_seen_at is older than this many seconds.",
    ),
) -> DevicesListResponse:
    if not include_health:
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

    # include_health=True
    from baseliner_server.schemas.admin_list import RunSummaryLite, DeviceHealth

    runs_ranked = (
        select(
            Run.id.label("run_id"),
            Run.device_id.label("device_id"),
            Run.started_at.label("started_at"),
            Run.ended_at.label("ended_at"),
            Run.status.label("status"),
            Run.agent_version.label("agent_version"),
            Run.effective_policy_hash.label("effective_policy_hash"),
            Run.summary.label("summary"),
            func.row_number()
            .over(partition_by=Run.device_id, order_by=(Run.started_at.desc(), Run.id.desc()))
            .label("rn"),
        )
    ).subquery()

    stmt = (
        select(Device, runs_ranked)
        .outerjoin(runs_ranked, (runs_ranked.c.device_id == Device.id) & (runs_ranked.c.rn == 1))
        .order_by(desc(Device.last_seen_at), desc(Device.enrolled_at))
        .offset(offset)
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    # NOTE: sqlite/postgres datetime handling can yield a mix of naive + tz-aware
    # datetimes depending on driver + column configuration. Always normalize to
    # UTC-aware datetimes before subtracting, otherwise Python raises:
    #   TypeError: can't subtract offset-naive and offset-aware datetimes
    now = datetime.now(timezone.utc)

    def _age_seconds(then: datetime | None) -> int | None:
        if not then:
            return None
        t = then
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        else:
            t = t.astimezone(timezone.utc)
        return int((now - t).total_seconds())

    items_out: list[DeviceSummary] = []
    for row in rows:
        d: Device = row[0]
        m = row._mapping  # labeled columns from runs_ranked live here

        run_id = m.get("run_id")
        last_run_at: datetime | None = None
        last_run_status: str | None = None
        last_run_obj: RunSummaryLite | None = None

        if run_id is not None:
            last_run_status = _status(m.get("status"))
            started_at = m.get("started_at")
            ended_at = m.get("ended_at")
            last_run_at = ended_at or started_at

            last_run_obj = RunSummaryLite(
                id=str(run_id),
                started_at=started_at,
                ended_at=ended_at,
                status=last_run_status,
                agent_version=m.get("agent_version"),
                effective_policy_hash=m.get("effective_policy_hash"),
                summary=(m.get("summary") or {}),
            )

        seen_age_s = _age_seconds(d.last_seen_at)
        run_age_s = _age_seconds(last_run_at)

        offline = (seen_age_s is None) or (seen_age_s > int(offline_after_seconds))
        stale = (run_age_s is None) or (run_age_s > int(stale_after_seconds))
        last_run_failed = bool(last_run_status and last_run_status.lower() != "succeeded")

        if offline:
            health_status = "offline"
            reason = "device has not checked in recently"
        elif last_run_failed:
            health_status = "warn"
            reason = "latest run failed"
        elif stale:
            health_status = "warn"
            reason = "stale"
        else:
            health_status = "ok"
            reason = None

        items_out.append(
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
                last_run=last_run_obj,
                health=DeviceHealth(
                    status=health_status,
                    now=now,
                    last_seen_at=d.last_seen_at,
                    last_run_at=last_run_at,
                    last_run_status=last_run_status,
                    seen_age_seconds=seen_age_s,
                    run_age_seconds=run_age_s,
                    stale=bool(stale),
                    offline=bool(offline),
                    reason=reason,
                ),
            )
        )

    return DevicesListResponse(items=items_out, limit=limit, offset=offset)


@router.get("/admin/runs", response_model=RunsListResponse, dependencies=[Depends(require_admin)])
def list_runs(
    db: Session = Depends(get_db),
    device_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RunsListResponse:
    base = select(Run)
    if device_id:
        base = base.where(Run.device_id == device_id)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    stmt = base.order_by(desc(Run.started_at)).offset(offset).limit(limit)
    runs = list(db.scalars(stmt).all())

    return RunsListResponse(
        items=[
            RunSummary(
                id=str(r.id),
                device_id=str(r.device_id),
                started_at=r.started_at,
                ended_at=r.ended_at,
                status=_status(r.status),
                agent_version=r.agent_version,
                summary=r.summary or {},
                policy_snapshot=r.policy_snapshot or {},
            )
            for r in runs
        ],
        limit=limit,
        offset=offset,
        total=int(total),
    )


@router.get(
    "/admin/runs/{run_id}",
    response_model=RunDetailResponse,
    dependencies=[Depends(require_admin)],
)
def get_run_detail(
    run_id: str = Path(...),
    db: Session = Depends(get_db),
) -> RunDetailResponse:
    run = db.scalar(select(Run).where(Run.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = list(db.scalars(select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.ordinal.asc())).all())
    logs = list(db.scalars(select(LogEvent).where(LogEvent.run_id == run.id).order_by(LogEvent.ts.asc())).all())

    return RunDetailResponse(
        id=str(run.id),
        device_id=str(run.device_id),
        started_at=run.started_at,
        ended_at=run.ended_at,
        status=_status(run.status) or "unknown",
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
                status_detect=_status(i.status_detect) or "unknown",
                status_remediate=_status(i.status_remediate) or "unknown",
                status_validate=_status(i.status_validate) or "unknown",
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
                level=_status(l.level) or "info",
                message=l.message,
                data=l.data or {},
                run_item_id=str(l.run_item_id) if l.run_item_id else None,
            )
            for l in logs
        ],
    )

@router.post(
    "/admin/compile",
    dependencies=[Depends(require_admin)],
)
def compile_policy_for_device(device_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Debug endpoint: compile effective policy snapshot for a device.

    Called like:
      POST /api/v1/admin/compile?device_id=<uuid>
    """
    dev = db.get(Device, device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    snap = compile_effective_policy(db, dev)
    return {"device_id": str(dev.id), "mode": snap.mode, "policy": snap.policy, "meta": snap.meta}

