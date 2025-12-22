from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request

from baseliner_server.db.models import AuditLog


def _get_correlation_id(request: Request) -> str | None:
    try:
        v = getattr(request.state, "correlation_id", None)
        return str(v) if v else None
    except Exception:
        return None


def _get_remote_addr(request: Request) -> str | None:
    # Prefer what the ASGI server thinks the remote addr is.
    try:
        if request.client and request.client.host:
            return str(request.client.host)
    except Exception:
        pass

    # Fallback for reverse proxy deployments.
    try:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip() or None
    except Exception:
        pass

    return None


def emit_admin_audit(
    db: Session,
    request: Request,
    *,
    actor_id: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an admin action in the audit log.

    NOTE: This function does **not** commit. Callers should add it to the same
    transaction as the admin mutation they are performing.
    """

    row = AuditLog(
        actor_type="admin_key",
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_method=request.method,
        request_path=request.url.path,
        correlation_id=_get_correlation_id(request),
        remote_addr=_get_remote_addr(request),
        data=data or {},
    )

    db.add(row)
    return row
