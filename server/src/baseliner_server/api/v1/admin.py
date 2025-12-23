import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from baseliner_server.api.deps import get_db, hash_token, require_admin, require_admin_actor
from baseliner_server.core.policy_validation import (
    PolicyDocValidationError,
    validate_and_normalize_document,
)
from baseliner_server.db.models import (
    AssignmentMode,
    AuditLog,
    Device,
    DeviceStatus,
    EnrollToken,
    LogEvent,
    Policy,
    PolicyAssignment,
    Run,
    RunItem,
    RunKind,
)
from baseliner_server.schemas.admin import (
    AssignPolicyRequest,
    AssignPolicyResponse,
    ClearAssignmentsResponse,
    CreateEnrollTokenRequest,
    CreateEnrollTokenResponse,
    DeleteDeviceResponse,
    DeviceAssignmentsResponse,
    DeviceDebugResponse,
    PolicyAssignmentDebugOut,
    PolicyAssignmentOut,
    RestoreDeviceResponse,
    RevokeDeviceTokenResponse,
    RunDebugSummary,
)
from baseliner_server.schemas.admin_list import (
    DevicesListResponse,
    DeviceSummary,
    RunsListResponse,
    RunSummary,
)
from baseliner_server.schemas.audit import AuditEvent, AuditListResponse
from baseliner_server.schemas.device_runs import DeviceRunsResponse, RunRollup
from baseliner_server.schemas.maintenance import PruneCounts, PruneRequest, PruneResponse
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.policy_admin import UpsertPolicyRequest, UpsertPolicyResponse
from baseliner_server.schemas.run_detail import LogEventDetail, RunDetailResponse, RunItemDetail
from baseliner_server.services.audit import emit_admin_audit
from baseliner_server.services.policy_compiler import compile_effective_policy

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
)
def create_enroll_token(
    request: Request,
    payload: CreateEnrollTokenRequest,
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> CreateEnrollTokenResponse:
    raw = secrets.token_urlsafe(24)
    tok = EnrollToken(
        token_hash=hash_token(raw),
        created_at=utcnow(),
        expires_at=payload.expires_at,
        used_at=None,
        note=payload.note,
    )
    db.add(tok)
    db.flush()

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="enroll_token.create",
        target_type="enroll_token",
        target_id=str(tok.id),
        data={
            "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
            "note": payload.note,
        },
    )

    db.commit()
    return CreateEnrollTokenResponse(enroll_token=raw, expires_at=payload.expires_at)


@router.post(
    "/admin/assign-policy",
    response_model=AssignPolicyResponse,
)
def assign_policy(
    request: Request,
    payload: AssignPolicyRequest,
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> AssignPolicyResponse:
    device = db.scalar(select(Device).where(Device.id == payload.device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status != DeviceStatus.active:
        raise HTTPException(status_code=409, detail="Device is deactivated")

    policy = db.scalar(select(Policy).where(Policy.name == payload.policy_name))
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    mode = (
        AssignmentMode.enforce
        if (payload.mode or "").lower() == "enforce"
        else AssignmentMode.audit
    )

    existing = db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.device_id == device.id,
            PolicyAssignment.policy_id == policy.id,
        )
    )

    created = False
    if existing:
        existing.mode = mode
        existing.priority = payload.priority
        db.add(existing)
    else:
        created = True
        db.add(
            PolicyAssignment(
                device_id=device.id,
                policy_id=policy.id,
                mode=mode,
                priority=payload.priority,
            )
        )

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="assignment.set",
        target_type="device",
        target_id=str(device.id),
        data={
            "policy_id": str(policy.id),
            "policy_name": policy.name,
            "mode": _status(mode) or str(mode),
            "priority": int(payload.priority),
            "created": created,
        },
    )

    db.commit()
    return AssignPolicyResponse(ok=True)


@router.get(
    "/admin/devices/{device_id}/assignments",
    response_model=DeviceAssignmentsResponse,
    dependencies=[Depends(require_admin)],
)
def list_device_assignments(
    device_id: uuid.UUID = Path(..., description="Device UUID"),
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

    return DeviceAssignmentsResponse(device_id=str(device_id), assignments=out)


@router.delete(
    "/admin/devices/{device_id}/assignments",
    response_model=ClearAssignmentsResponse,
)
def clear_device_assignments(
    request: Request,
    device_id: uuid.UUID = Path(..., description="Device UUID"),
    admin_actor: str = Depends(require_admin_actor),
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

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="assignment.clear",
        target_type="device",
        target_id=str(device.id),
        data={"removed": int(removed or 0)},
    )

    db.commit()
    return ClearAssignmentsResponse(device_id=str(device_id), removed=int(removed or 0))


@router.delete(
    "/admin/devices/{device_id}",
    response_model=DeleteDeviceResponse,
)
def delete_device(
    request: Request,
    device_id: uuid.UUID = Path(..., description="Device UUID"),
    reason: str | None = Query(
        None, description="Optional deletion reason (stored for audit/debug)"
    ),
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> DeleteDeviceResponse:
    """Soft-delete (deactivate) a device and revoke its current device token.

    This is intentionally *not* a hard delete. Runs remain for history.

    Side effects:
      - device.status => deleted
      - device.deleted_at (+ optional deleted_reason)
      - device token revoked (revoked_auth_token_hash captures the old token hash;
        auth_token_hash is rotated so future tokens can be minted without ambiguity)
      - all active policy assignments removed
    """

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Idempotent: deleting an already-deleted device is OK.
    already_deleted = device.status != DeviceStatus.active

    removed = (
        db.query(PolicyAssignment)
        .filter(PolicyAssignment.device_id == device.id)
        .delete(synchronize_session=False)
    )

    if already_deleted:
        # Do not rotate token hashes again; that would break the ability to map an
        # old (already revoked) token to this device for a clear 403.
        if reason and not device.deleted_reason:
            device.deleted_reason = reason
    else:
        now = utcnow()

        # Revoke token: keep the previous hash so we can return a clear 403 for old tokens.
        device.revoked_auth_token_hash = device.auth_token_hash
        device.token_revoked_at = now

        # Rotate the active token hash to an unknown value (not returned).
        device.auth_token_hash = hash_token(secrets.token_urlsafe(32))

        device.status = DeviceStatus.deleted
        device.deleted_at = now
        device.deleted_reason = reason

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="device.delete",
        target_type="device",
        target_id=str(device.id),
        data={
            "already_deleted": bool(already_deleted),
            "reason": reason,
            "assignments_removed": int(removed or 0),
        },
    )

    db.add(device)
    db.commit()

    return DeleteDeviceResponse(
        device_id=str(device.id),
        status=device.status.value if hasattr(device.status, "value") else str(device.status),
        deleted_at=device.deleted_at,
        deleted_reason=device.deleted_reason,
        token_revoked_at=device.token_revoked_at,
        assignments_removed=int(removed or 0),
    )


@router.post(
    "/admin/devices/{device_id}/restore",
    response_model=RestoreDeviceResponse,
)
def restore_device(
    request: Request,
    device_id: uuid.UUID = Path(..., description="Device UUID"),
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> RestoreDeviceResponse:
    """Restore a soft-deleted device (reactivate) and mint a fresh device token."""

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status == DeviceStatus.active:
        raise HTTPException(status_code=409, detail="Device is already active")

    now = utcnow()
    new_token = secrets.token_urlsafe(32)
    device.auth_token_hash = hash_token(new_token)
    device.status = DeviceStatus.active
    device.deleted_at = None
    device.deleted_reason = None

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="device.restore",
        target_type="device",
        target_id=str(device.id),
        data={},
    )

    db.add(device)
    db.commit()

    return RestoreDeviceResponse(
        device_id=str(device.id),
        status=device.status.value if hasattr(device.status, "value") else str(device.status),
        restored_at=now,
        device_token=new_token,
    )


@router.post(
    "/admin/devices/{device_id}/revoke-token",
    response_model=RevokeDeviceTokenResponse,
)
def revoke_device_token(
    request: Request,
    device_id: uuid.UUID = Path(..., description="Device UUID"),
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> RevokeDeviceTokenResponse:
    """Revoke the current device token and mint a new one."""

    device = db.scalar(select(Device).where(Device.id == device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status != DeviceStatus.active:
        raise HTTPException(status_code=409, detail="Device is deactivated")

    now = utcnow()
    new_token = secrets.token_urlsafe(32)

    device.revoked_auth_token_hash = device.auth_token_hash
    device.token_revoked_at = now
    device.auth_token_hash = hash_token(new_token)

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="device.revoke_token",
        target_type="device",
        target_id=str(device.id),
        data={},
    )

    db.add(device)
    db.commit()

    return RevokeDeviceTokenResponse(
        device_id=str(device.id),
        status=device.status.value if hasattr(device.status, "value") else str(device.status),
        token_revoked_at=now,
        device_token=new_token,
    )


@router.get(
    "/admin/devices/{device_id}/debug",
    response_model=DeviceDebugResponse,
    dependencies=[Depends(require_admin)],
)
def debug_device_bundle(
    device_id: uuid.UUID = Path(..., description="Device UUID"),
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
                select(RunItem).where(RunItem.run_id == last_run.id).order_by(RunItem.ordinal.asc())
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
            correlation_id=last_run.correlation_id,
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
        status=_status(device.status),
        deleted_at=device.deleted_at,
        deleted_reason=device.deleted_reason,
        token_revoked_at=device.token_revoked_at,
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
    device_id: uuid.UUID = Path(..., description="Device UUID"),
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
                    select(RunItem).where(RunItem.run_id == r.id).order_by(RunItem.ordinal.asc())
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

                        return (
                            _sf(it.status_detect)
                            or _sf(it.status_remediate)
                            or _sf(it.status_validate)
                        )
                    except Exception:
                        return False

                items_failed = sum(1 for it in its if _it_failed(it))

        items_out.append(
            RunRollup(
                id=str(r.id),
                device_id=str(r.device_id),
                correlation_id=r.correlation_id,
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
)
def upsert_policy(
    request: Request,
    payload: UpsertPolicyRequest,
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> UpsertPolicyResponse:
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

    created = False

    if existing:
        existing.description = payload.description
        existing.schema_version = payload.schema_version
        existing.document = normalized_doc
        existing.is_active = payload.is_active
        existing.updated_at = utcnow()
        db.add(existing)
        policy_id = str(existing.id)
    else:
        created = True
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
        db.flush()
        policy_id = str(policy.id)

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="policy.upsert",
        target_type="policy",
        target_id=policy_id,
        data={
            "name": payload.name,
            "is_active": bool(payload.is_active),
            "created": bool(created),
        },
    )

    db.commit()
    return UpsertPolicyResponse(policy_id=policy_id, name=payload.name, is_active=payload.is_active)


@router.get(
    "/admin/audit",
    response_model=AuditListResponse,
    dependencies=[Depends(require_admin)],
)
def list_audit_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None, description="Pagination cursor from a previous response"),
    action: str | None = Query(None, description="Filter by action"),
    target_type: str | None = Query(None, description="Filter by target_type"),
    target_id: str | None = Query(None, description="Filter by target_id"),
) -> AuditListResponse:
    """List audit events (admin actions), newest first."""

    def _parse_cursor(value: str) -> tuple[datetime, uuid.UUID]:
        try:
            ts_s, id_s = value.split("|", 1)
            # fromisoformat does not accept 'Z' directly
            ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
            return ts, uuid.UUID(id_s)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    stmt = select(AuditLog)

    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)

    if cursor:
        cur_ts, cur_id = _parse_cursor(cursor)
        stmt = stmt.where(
            or_(AuditLog.ts < cur_ts, and_(AuditLog.ts == cur_ts, AuditLog.id < cur_id))
        )

    stmt = stmt.order_by(desc(AuditLog.ts), desc(AuditLog.id)).limit(limit + 1)

    rows = list(db.scalars(stmt).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = f"{last.ts.isoformat()}|{last.id}"
        rows = rows[:limit]

    items = [
        AuditEvent(
            id=str(r.id),
            ts=r.ts,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            request_method=r.request_method,
            request_path=r.request_path,
            correlation_id=r.correlation_id,
            remote_addr=r.remote_addr,
            data=r.data or {},
        )
        for r in rows
    ]

    return AuditListResponse(items=items, limit=limit, next_cursor=next_cursor)


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
    include_deleted: bool = Query(
        False,
        description="If true, include soft-deleted devices in the list.",
    ),
) -> DevicesListResponse:
    from baseliner_server.schemas.admin_list import DeviceHealth, RunSummaryLite

    runs_ranked_any = (
        select(
            Run.id.label("run_id"),
            Run.kind.label("run_kind"),
            Run.device_id.label("device_id"),
            Run.started_at.label("started_at"),
            Run.ended_at.label("ended_at"),
            Run.status.label("status"),
            Run.agent_version.label("agent_version"),
            Run.correlation_id.label("correlation_id"),
            Run.effective_policy_hash.label("effective_policy_hash"),
            Run.summary.label("summary"),
            func.row_number()
            .over(
                partition_by=Run.device_id,
                order_by=(Run.started_at.desc(), Run.id.desc()),
            )
            .label("rn"),
        )
    ).subquery()

    runs_ranked_apply = (
        select(
            Run.id.label("apply_run_id"),
            Run.kind.label("apply_run_kind"),
            Run.device_id.label("apply_device_id"),
            Run.started_at.label("apply_started_at"),
            Run.ended_at.label("apply_ended_at"),
            Run.status.label("apply_status"),
            Run.agent_version.label("apply_agent_version"),
            Run.correlation_id.label("apply_correlation_id"),
            Run.effective_policy_hash.label("apply_effective_policy_hash"),
            Run.summary.label("apply_summary"),
            func.row_number()
            .over(
                partition_by=Run.device_id,
                order_by=(Run.started_at.desc(), Run.id.desc()),
            )
            .label("rn"),
        )
        .where(Run.kind == RunKind.apply)
    ).subquery()

    stmt = select(Device, runs_ranked_any, runs_ranked_apply)
    if not include_deleted:
        stmt = stmt.where(Device.status == DeviceStatus.active)

    stmt = (
        stmt.outerjoin(
            runs_ranked_any,
            (runs_ranked_any.c.device_id == Device.id) & (runs_ranked_any.c.rn == 1),
        )
        .outerjoin(
            runs_ranked_apply,
            (runs_ranked_apply.c.apply_device_id == Device.id)
            & (runs_ranked_apply.c.rn == 1),
        )
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
        m = row._mapping

        # Latest run (apply or heartbeat).
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
                kind=_status(m.get("run_kind")),
                correlation_id=m.get("correlation_id"),
                started_at=started_at,
                ended_at=ended_at,
                status=last_run_status,
                agent_version=m.get("agent_version"),
                effective_policy_hash=m.get("effective_policy_hash"),
                summary=(m.get("summary") or {}),
            )

        # Latest *apply* run (compliance), ignoring heartbeat runs.
        apply_run_id = m.get("apply_run_id")
        last_apply_run_at: datetime | None = None
        last_apply_run_status: str | None = None
        last_apply_run_obj: RunSummaryLite | None = None

        if apply_run_id is not None:
            last_apply_run_status = _status(m.get("apply_status"))
            started_at = m.get("apply_started_at")
            ended_at = m.get("apply_ended_at")
            last_apply_run_at = ended_at or started_at

            last_apply_run_obj = RunSummaryLite(
                id=str(apply_run_id),
                kind=_status(m.get("apply_run_kind")),
                correlation_id=m.get("apply_correlation_id"),
                started_at=started_at,
                ended_at=ended_at,
                status=last_apply_run_status,
                agent_version=m.get("apply_agent_version"),
                effective_policy_hash=m.get("apply_effective_policy_hash"),
                summary=(m.get("apply_summary") or {}),
            )

        health_obj: DeviceHealth | None = None
        if include_health or last_run_at is not None or d.last_seen_at is not None:
            seen_age_s = _age_seconds(d.last_seen_at)
            run_age_s = _age_seconds(last_run_at)
            apply_run_age_s = _age_seconds(last_apply_run_at)

            offline = (seen_age_s is None) or (seen_age_s > int(offline_after_seconds))
            stale = (apply_run_age_s is None) or (
                apply_run_age_s > int(stale_after_seconds)
            )
            last_apply_failed = bool(
                last_apply_run_status and last_apply_run_status.lower() != "succeeded"
            )

            if offline:
                health_status = "offline"
                reason = "device has not checked in recently"
            elif last_apply_failed:
                health_status = "warn"
                reason = "latest apply run failed"
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
                last_apply_run_at=last_apply_run_at,
                last_apply_run_status=last_apply_run_status,
                seen_age_seconds=seen_age_s,
                run_age_seconds=run_age_s,
                apply_run_age_seconds=apply_run_age_s,
                stale=bool(stale),
                offline=bool(offline),
                reason=reason,
            )

        items_out.append(
            DeviceSummary(
                id=str(d.id),
                device_key=d.device_key,
                status=_status(d.status),
                deleted_at=d.deleted_at,
                deleted_reason=d.deleted_reason,
                token_revoked_at=d.token_revoked_at,
                hostname=d.hostname,
                os=d.os,
                os_version=d.os_version,
                arch=d.arch,
                agent_version=d.agent_version,
                enrolled_at=d.enrolled_at,
                last_seen_at=d.last_seen_at,
                tags=d.tags or {},
                last_run=last_run_obj,
                last_apply_run=last_apply_run_obj,
                health=health_obj,
            )
        )

    return DevicesListResponse(items=items_out, limit=limit, offset=offset)


@router.get("/admin/runs", response_model=RunsListResponse, dependencies=[Depends(require_admin)])
def list_runs(
    db: Session = Depends(get_db),
    device_id: uuid.UUID | None = Query(None),
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
                correlation_id=r.correlation_id,
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
    run_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
) -> RunDetailResponse:
    run = db.scalar(select(Run).where(Run.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = list(
        db.scalars(
            select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.ordinal.asc())
        ).all()
    )
    logs = list(
        db.scalars(
            select(LogEvent).where(LogEvent.run_id == run.id).order_by(LogEvent.ts.asc())
        ).all()
    )

    return RunDetailResponse(
        id=str(run.id),
        device_id=str(run.device_id),
        correlation_id=run.correlation_id,
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
                id=str(log_event.id),
                ts=log_event.ts,
                level=_status(log_event.level) or "info",
                message=log_event.message,
                data=log_event.data or {},
                run_item_id=str(log_event.run_item_id) if log_event.run_item_id else None,
            )
            for log_event in logs
        ],
    )


@router.post(
    "/admin/compile",
    dependencies=[Depends(require_admin)],
)
def compile_policy_for_device(
    device_id: uuid.UUID, db: Session = Depends(get_db)
) -> dict[str, Any]:
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
    return [seq[i : i + size] for i in range(0, len(seq), size)]


@router.post(
    "/admin/maintenance/prune",
    response_model=PruneResponse,
)
def prune_runs(
    request: Request,
    payload: PruneRequest,
    admin_actor: str = Depends(require_admin_actor),
    db: Session = Depends(get_db),
) -> PruneResponse:
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
            db.scalar(select(func.count()).select_from(RunItem).where(RunItem.run_id.in_(run_ids)))
            or 0
        )
        counts_logs = int(
            db.scalar(
                select(func.count()).select_from(LogEvent).where(LogEvent.run_id.in_(run_ids))
            )
            or 0
        )

    if payload.dry_run:
        emit_admin_audit(
            db,
            request,
            actor_id=admin_actor,
            action="maintenance.prune",
            data={
                "dry_run": True,
                "keep_days": int(payload.keep_days),
                "keep_runs_per_device": int(payload.keep_runs_per_device),
                "runs_targeted": int(runs_targeted),
                "counts": {
                    "runs": int(counts_runs),
                    "run_items": int(counts_items),
                    "log_events": int(counts_logs),
                },
            },
        )
        db.commit()
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
            db.query(LogEvent).filter(LogEvent.run_id.in_(chunk)).delete(synchronize_session=False)
            or 0
        )
        deleted_items += int(
            db.query(RunItem).filter(RunItem.run_id.in_(chunk)).delete(synchronize_session=False)
            or 0
        )
        deleted_runs += int(
            db.query(Run).filter(Run.id.in_(chunk)).delete(synchronize_session=False) or 0
        )

    emit_admin_audit(
        db,
        request,
        actor_id=admin_actor,
        action="maintenance.prune",
        data={
            "dry_run": False,
            "keep_days": int(payload.keep_days),
            "keep_runs_per_device": int(payload.keep_runs_per_device),
            "runs_targeted": int(runs_targeted),
            "counts": {
                "runs": int(deleted_runs),
                "run_items": int(deleted_items),
                "log_events": int(deleted_logs),
            },
        },
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
