from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

# NOTE: dependencies live in api.deps; core.auth only contains the auth logic.
from baseliner_server.api.deps import get_current_device, get_db
from baseliner_server.services.policy_compiler import compile_effective_policy
from baseliner_server.db.models import Device, LogEvent, Run, RunItem
from baseliner_server.db.models import StepStatus, RunStatus
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.report import SubmitReportRequest, SubmitReportResponse


router = APIRouter(tags=["device"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_step_status(value: str | None) -> StepStatus:
    """
    Accept legacy/agent strings and map to DB enum values used in previous dev versions
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


def _summary_int(summary: dict[str, Any], *keys: str) -> int | None:
    if not isinstance(summary, dict):
        return None
    for k in keys:
        if k not in summary:
            continue
        v = summary.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str) and v.strip():
                return int(float(v.strip()))
        except Exception:
            continue
    return None


def _is_item_failed(item: Any) -> bool:
    """Determine whether a reported item should be treated as failed.

    For MVP we enforce strong invariants:
      - a run is failed if any item is failed
      - an item is failed if it has error.type or any step status is fail/failed
    """
    try:
        err = getattr(item, "error", None) or {}
        if isinstance(err, dict) and err.get("type"):
            return True

        def _sf(v: str | None) -> bool:
            s = (v or "").strip().lower()
            return s in ("fail", "failed")

        return (
            _sf(getattr(item, "status_detect", None))
            or _sf(getattr(item, "status_remediate", None))
            or _sf(getattr(item, "status_validate", None))
        )
    except Exception:
        return False


def _normalize_run_status(payload_status: str | None, *, items_total: int, items_failed: int) -> RunStatus:
    """Normalize run status for storage.

    Device reports should always represent a completed execution.
    We override ambiguous statuses (running/partial/etc) to keep invariants.
    """
    if items_total == 0:
        status = (payload_status or "").strip().lower()
        if status in ("fail", "failed", "error"):
            return RunStatus.failed
        return RunStatus.succeeded
    return RunStatus.failed if items_failed > 0 else RunStatus.succeeded


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
        schema_version="1",
        mode=snap.mode,
        document=snap.policy,
        effective_policy_hash=str(snap.meta.get("effective_hash") or ""),
        sources=snap.meta.get("sources") or [],
        compile=snap.meta.get("compile") or {},
    )
    return resp


@router.post("/device/reports", response_model=SubmitReportResponse)
def submit_report(
    payload: SubmitReportRequest,
    request: Request,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db),
) -> SubmitReportResponse:
    snapshot = normalize_policy_snapshot(payload.policy_snapshot or {})

    # Authoritative counts from items (do not trust client summary).
    items_total_calc = len(payload.items or [])
    items_failed_calc = sum(1 for it in (payload.items or []) if _is_item_failed(it))
    items_changed_calc = sum(1 for it in (payload.items or []) if bool(getattr(it, "changed", False)))

    ended_at = payload.ended_at or utcnow()
    status = _normalize_run_status(payload.status, items_total=items_total_calc, items_failed=items_failed_calc)

    summary = payload.summary or {}
    if not isinstance(summary, dict):
        summary = {}

    # Allow duration to be supplied by the agent (optional).
    duration_ms = _summary_int(summary, "duration_ms", "durationMs")

    # Ensure canonical summary keys exist for operator QoL endpoints.
    summary["items_total"] = int(items_total_calc)
    summary["items_failed"] = int(items_failed_calc)
    summary["items_changed"] = int(items_changed_calc)
    if duration_ms is not None:
        summary["duration_ms"] = int(duration_ms)

    # Optional legacy mirror for older tooling.
    summary.setdefault("itemsTotal", summary["items_total"])
    summary.setdefault("failed", summary["items_failed"])

    run = Run(
        device_id=device.id,
        started_at=payload.started_at,
        ended_at=ended_at,
        status=status,
        agent_version=payload.agent_version,
        correlation_id=getattr(getattr(request, "state", None), "correlation_id", None),
        effective_policy_hash=payload.effective_policy_hash,  # agent sends server hash (or fallback)
        policy_snapshot=snapshot,
        summary=summary,
    )
    db.add(run)
    db.flush()  # run.id available

    # Items (we store ordinal so logs can reference it)
    ordinal_to_item_id: dict[int, uuid.UUID] = {}
    for item in (payload.items or []):
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
    if payload.status and payload.status != status.value:
        # Useful breadcrumb for debugging client/server mismatch.
        db.add(
            LogEvent(
                run_id=run.id,
                run_item_id=None,
                ts=utcnow(),
                level="warning",
                message="server normalized run status",
                data={"reported": payload.status, "stored": status.value, "items_failed": items_failed_calc},
            )
        )

    for log in (payload.logs or []):
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
