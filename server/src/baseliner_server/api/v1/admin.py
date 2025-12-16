import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

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
)
from baseliner_server.schemas.admin_list import (
    DeviceSummary,
    DevicesListResponse,
    RunSummary,
    RunsListResponse,
)
from baseliner_server.schemas.policy_admin import UpsertPolicyRequest, UpsertPolicyResponse
from baseliner_server.schemas.run_detail import RunDetailResponse, RunItemDetail, LogEventDetail

router = APIRouter(tags=["admin"])


def utcnow() -> datetime:
    # Always return tz-aware UTC datetime.
    # Postgres returns tz-aware for timezone=True columns; keeping utcnow aware avoids
    # offset-naive vs offset-aware subtraction errors.
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    """
    Normalize datetimes to tz-aware UTC for calculations.
    Treat naive datetimes as UTC (common in sqlite/test contexts).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        # Keep DB values consistent: store expires_at as UTC-aware when present.
        expires_at=_as_utc(payload.expires_at),
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
    now = utcnow()  # aware

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

        seen_at = _as_utc(d.last_seen_at)
        run_at = _as_utc(last_run_at)

        seen_age_s = int((now - seen_at).total_seconds()) if seen_at else None
        run_age_s = int((now - run_at).total_seconds()) if run_at else None

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
