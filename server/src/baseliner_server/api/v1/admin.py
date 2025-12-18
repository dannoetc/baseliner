import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from baseliner_server.services.policy_compiler import compile_effective_policy
from baseliner_server.core.policy_validation import PolicyDocValidationError, validate_and_normalize_document
from baseliner_server.schemas.device_runs import DeviceRunsResponse, RunRollup
from baseliner_server.schemas.maintenance import PruneRequest, PruneResponse, PruneCounts
from baseliner_server.core.policy_validation import PolicyDocValidationError, validate_and_normalize_document

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


def _summary_int(summary: dict[str, Any], *keys: str) -> int | None:
    """Pull an int from a run.summary dict using the first matching key."""
    if not isinstance(summary, dict):
        return None

    for k in keys:
        if k not in summary:
            continue
        v = summary.get(k)
        if v is None:
            continue
        try:
            # handles int/float/"123"
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str) and v.strip():
                return int(float(v.strip()))
        except Exception:
            continue

    return None


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

        # QoL: quick counts + duration (so operators don't have to open run detail)
        def _is_failed(it: RunItemDetail) -> bool:
            err = it.error or {}
            if isinstance(err, dict) and err.get("type"):
                return True
            for s in (it.status_detect, it.status_remediate, it.status_validate):
                if (s or "").lower() in ("fail", "failed"):
                    return True
            return False

        items_total = len(last_items_out)
        items_failed = sum(1 for it in last_items_out if _is_failed(it))
        items_changed = sum(1 for it in last_items_out if bool(it.changed))

        duration_ms: int | None = None
        if last_run.started_at and last_run.ended_at:
            duration_ms = int((last_run.ended_at - last_run.started_at).total_seconds() * 1000)

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
            items_total=items_total,
            items_failed=items_failed,
            items_changed=items_changed,
            duration_ms=duration_ms,
        )

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


@router.get(
    "/admin/devices/{device_id}/runs",
    response_model=DeviceRunsResponse,
    dependencies=[Depends(require_admin)],
)
def list_device_runs(
    device_id: str = Path(..., description="Device UUID"),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DeviceRunsResponse:
    """Operator QoL: list recent runs for a device.

    This is a convenience wrapper for quickly viewing run history without
    fetching full run details.
    """

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    base = select(Run).where(Run.device_id == device.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    stmt = base.order_by(desc(Run.started_at), desc(Run.id)).offset(offset).limit(limit)
    runs = list(db.scalars(stmt).all())

    items_out: list[RunRollup] = []
    for r in runs:
        summary = (r.summary or {}) if isinstance(r.summary, dict) else {}

        items_total = _summary_int(summary, "items_total", "itemsTotal")
        items_failed = _summary_int(summary, "items_failed", "itemsFailed", "failed")
        items_changed = _summary_int(summary, "items_changed", "itemsChanged")
        duration_ms = _summary_int(summary, "duration_ms", "durationMs")

        # Fallbacks for older runs that predate these summary fields.
        if duration_ms is None and r.started_at and r.ended_at:
            try:
                duration_ms = int((r.ended_at - r.started_at).total_seconds() * 1000)
            except Exception:
                duration_ms = None

        if items_total is None or items_failed is None or items_changed is None:
            # Best-effort compute from items (small limits; acceptable for admin).
            its = list(
                db.scalars(
                    select(RunItem)
                    .where(RunItem.run_id == r.id)
                    .order_by(RunItem.ordinal.asc())
                ).all()
            )
            if items_total is None:
                items_total = len(its)

            if items_changed is None:
                items_changed = sum(1 for it in its if bool(it.changed))

            if items_failed is None:
                def _it_failed(it: RunItem) -> bool:
                    try:
                        err = it.error or {}
                        if isinstance(err, dict) and err.get("type"):
                            return True

                        def _sf(v: Any) -> bool:
                            s = ("" if v is None else _status(v) or str(v)).strip().lower()
                            return s in ("fail", "failed")

                        return _sf(it.status_detect) or _sf(it.status_remediate) or _sf(it.status_validate)
                    except Exception:
                        return False

                items_failed = sum(1 for it in its if _it_failed(it))

        items_out.append(
            RunRollup(
                id=str(r.id),
                device_id=str(r.device_id),
                started_at=r.started_at,
                ended_at=r.ended_at,
                status=_status(r.status),
                agent_version=r.agent_version,
                effective_policy_hash=r.effective_policy_hash,
                items_total=items_total,
                items_failed=items_failed,
                items_changed=items_changed,
                duration_ms=duration_ms,
                summary=summary,
                detail_path=f"/api/v1/admin/runs/{r.id}",
            )
        )

    return DeviceRunsResponse(
        device_id=str(device.id),
        items=items_out,
        limit=limit,
        offset=offset,
        total=int(total),
    )


@router.post(
    "/admin/policies",
    response_model=UpsertPolicyResponse,
    dependencies=[Depends(require_admin)],
)
def upsert_policy(payload: UpsertPolicyRequest, db: Session = Depends(get_db)) -> UpsertPolicyResponse:
    existing = db.scalar(select(Policy).where(Policy.name == payload.name))

    try:
        normalized_doc = validate_and_normalize_document(payload.document)
    except PolicyDocValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "policy document invalid",
                "errors": [{"path": er.path, "message": er.message} for er in e.errors],
            },
        )

    if existing:
        existing.description = payload.description
        existing.schema_version = payload.schema_version
        existing.document = normalized_doc
        existing.is_active = payload.is_active
        existing.updated_at = utcnow()
        db.add(existing)
        db.commit()
        return UpsertPolicyResponse(policy_id=str(existing.id), name=existing.name, is_active=existing.is_active)

    policy = Policy(
        name=payload.name,
        description=payload.description,
        schema_version=payload.schema_version,
        document=normalized_doc,
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
        description=(
            "If true, include last_run + computed health fields per device."
            " Basic last_run + health details are still included when false."
        ),
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

        health_obj: DeviceHealth | None = None

        # Provide basic health insight even when include_health=False so clients
        # consistently receive last_run + health metadata.
        if include_health or last_run_at is not None or d.last_seen_at is not None:
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

            health_obj = DeviceHealth(
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
            )

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
                health=health_obj,
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

def _chunked(seq: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [seq]
    return [seq[i:i + size] for i in range(0, len(seq), size)]


@router.post(
    "/admin/maintenance/prune",
    response_model=PruneResponse,
    dependencies=[Depends(require_admin)],
)
def prune_runs(payload: PruneRequest, db: Session = Depends(get_db)) -> PruneResponse:
    """Prune old run data to keep the database bounded.

    Rules:
      - keep runs newer than keep_days
      - keep at most keep_runs_per_device most-recent runs per device
      - delete in order: log_events -> run_items -> runs

    Use dry_run=true to see counts without deleting.
    """

    if payload.keep_days < 0:
        raise HTTPException(status_code=400, detail="keep_days must be >= 0")
    if payload.keep_runs_per_device < 0:
        raise HTTPException(status_code=400, detail="keep_runs_per_device must be >= 0")

    cutoff = utcnow() - timedelta(days=int(payload.keep_days))

    ranked = (
        select(
            Run.id.label("run_id"),
            Run.device_id.label("device_id"),
            Run.started_at.label("started_at"),
            func.row_number()
            .over(
                partition_by=Run.device_id,
                order_by=(Run.started_at.desc(), Run.id.desc()),
            )
            .label("rn"),
        )
    ).subquery()

    # rank condition: delete anything beyond the per-device keep limit.
    if int(payload.keep_runs_per_device) > 0:
        cond_rank = ranked.c.rn > int(payload.keep_runs_per_device)
    else:
        # keep_runs_per_device == 0 => delete all runs (subject to keep_days if keep_days>0)
        cond_rank = ranked.c.rn >= 1

    # age condition: delete anything older than cutoff (disabled if keep_days == 0)
    cond_age = ranked.c.started_at < cutoff if int(payload.keep_days) > 0 else False

    where_clause = cond_rank if cond_age is False else (cond_rank | cond_age)

    run_ids = [r[0] for r in db.execute(select(ranked.c.run_id).where(where_clause)).all()]

    runs_targeted = len(run_ids)

    counts_runs = runs_targeted
    counts_items = 0
    counts_logs = 0

    if run_ids:
        counts_items = int(
            db.scalar(
                select(func.count()).select_from(RunItem).where(RunItem.run_id.in_(run_ids))
            )
            or 0
        )
        counts_logs = int(
            db.scalar(
                select(func.count()).select_from(LogEvent).where(LogEvent.run_id.in_(run_ids))
            )
            or 0
        )

    if payload.dry_run:
        return PruneResponse(
            dry_run=True,
            keep_days=int(payload.keep_days),
            keep_runs_per_device=int(payload.keep_runs_per_device),
            cutoff=cutoff,
            runs_targeted=runs_targeted,
            counts=PruneCounts(runs=counts_runs, run_items=counts_items, log_events=counts_logs),
            notes={"mode": "dry_run"},
        )


    deleted_logs = 0
    deleted_items = 0
    deleted_runs = 0

    for chunk in _chunked(run_ids, int(payload.batch_size)):
        if not chunk:
            continue

        deleted_logs += int(
            db.query(LogEvent)
            .filter(LogEvent.run_id.in_(chunk))
            .delete(synchronize_session=False)
            or 0
        )
        deleted_items += int(
            db.query(RunItem)
            .filter(RunItem.run_id.in_(chunk))
            .delete(synchronize_session=False)
            or 0
        )
        deleted_runs += int(
            db.query(Run)
            .filter(Run.id.in_(chunk))
            .delete(synchronize_session=False)
            or 0
        )

    db.commit()

    return PruneResponse(
    dry_run=False,
    keep_days=int(payload.keep_days),
    keep_runs_per_device=int(payload.keep_runs_per_device),
    cutoff=cutoff,
    runs_targeted=runs_targeted,
    counts=PruneCounts(runs=deleted_runs, run_items=deleted_items, log_events=deleted_logs),
    notes={"mode": "deleted"},
)

