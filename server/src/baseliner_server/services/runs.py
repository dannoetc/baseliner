"""Run service helpers.

A couple of branches/tools referenced an intermediate service module
(``baseliner_server.services.runs``) to fetch run lists and run details. The
mainline API started with most logic in route handlers, but the policy/lifecycle
PowerShell harness is much nicer to maintain when the server has:

  - a stable, typed listing helper (list_runs)
  - a stable, typed detail helper (get_run)

This module intentionally returns *schema models* (not raw SQLAlchemy rows) so
routes can simply `return list_runs(...)` or `return get_run(...)`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from baseliner_server.db.models import Run, RunItem
from baseliner_server.schemas.admin_list import RunsListResponse, RunSummary
from baseliner_server.schemas.run_detail import LogEventDetail, RunItemDetail, RunOutFull


def _status(v: Any) -> Optional[str]:
    """Return a stable string for Enum-ish values."""
    if v is None:
        return None
    return getattr(v, "value", None) or str(v)


def list_runs(db: Session, *, limit: int = 100, offset: int = 0) -> RunsListResponse:
    """List runs with basic rollups.

    Uses an aggregate over RunItem rows to avoid N+1 queries.
    """
    total = db.scalar(select(func.count()).select_from(Run)) or 0

    items_agg = (
        select(
            RunItem.run_id.label("run_id"),
            func.count().label("items_total"),
            func.sum(case((RunItem.status_remediate == "fail", 1), else_=0)).label("items_failed"),
        )
        .group_by(RunItem.run_id)
        .subquery()
    )

    stmt = (
        select(Run, items_agg.c.items_total, items_agg.c.items_failed)
        .outerjoin(items_agg, items_agg.c.run_id == Run.id)
        .order_by(Run.started_at.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    items: list[RunSummary] = []
    for r, items_total, items_failed in rows:
        # Prefer `run.summary` if populated, but fall back to the aggregate.
        summary = r.summary or {}
        it_total = int(summary.get("items_total") or (items_total or 0))
        it_failed = int(summary.get("items_failed") or (items_failed or 0))

        items.append(
            RunSummary(
                id=str(r.id),
                device_id=str(r.device_id),
                status=_status(r.status) or "unknown",
                started_at=r.started_at,
                ended_at=r.ended_at,
                items_total=it_total,
                items_failed=it_failed,
            )
        )

    return RunsListResponse(total=int(total), items=items)


def get_run(db: Session, run_id: str) -> RunOutFull:
    """Get a run with items + logs.

    Raises HTTPException(404) if missing.
    """
    run = (
        db.query(Run)
        .options(joinedload(Run.items), joinedload(Run.logs))
        .filter(Run.id == run_id)
        .one_or_none()
    )

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items: list[RunItemDetail] = []
    for it in sorted(run.items or [], key=lambda x: int(getattr(x, "ordinal", 0))):
        items.append(
            RunItemDetail(
                ordinal=int(it.ordinal),
                resource_type=str(it.resource_type),
                resource_id=str(it.resource_id),
                name=str(it.name),
                status_detect=str(it.status_detect),
                status_remediate=str(it.status_remediate),
                status_validate=str(it.status_validate),
                compliant_before=it.compliant_before,
                compliant_after=it.compliant_after,
                changed=bool(it.changed),
                reboot_required=bool(it.reboot_required),
                started_at=it.started_at,
                ended_at=it.ended_at,
                evidence=it.evidence or {},
                error=it.error or {},
            )
        )

    logs: list[LogEventDetail] = []
    for le in sorted(run.logs or [], key=lambda x: x.ts):
        logs.append(
            LogEventDetail(
                ts=le.ts,
                level=str(le.level),
                message=str(le.message),
                data=le.data or {},
                run_item_ordinal=le.run_item_ordinal,
            )
        )

    return RunOutFull(
        id=str(run.id),
        device_id=str(run.device_id),
        status=_status(run.status) or "unknown",
        started_at=run.started_at,
        ended_at=run.ended_at,
        mode=run.mode,
        policy_name=run.policy_name,
        policy_version=run.policy_version,
        policy_compiled_hash=run.policy_compiled_hash,
        policy_compiled=run.policy_compiled or {},
        summary=run.summary or {},
        items=items,
        logs=logs,
    )


__all__ = ["list_runs", "get_run"]
