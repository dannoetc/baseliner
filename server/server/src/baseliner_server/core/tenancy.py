from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


# Phase 0: single-tenant default. All rows are assigned to this tenant.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_TENANT_NAME = "default"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TenantContext:
    """Tenant context for request-scoped operations.

    Phase 0:
      - always returns the default tenant
      - admin key remains global

    Future:
      - admin keys can be scoped to a tenant
      - device auth tokens implicitly map to a tenant via the device row
    """

    id: uuid.UUID


def get_tenant_context() -> TenantContext:
    # FastAPI dependency (no args): returns the current tenant context.
    return TenantContext(id=DEFAULT_TENANT_ID)


def ensure_default_tenant(db: "Session") -> None:
    """Ensure the default tenant exists.

    This is mainly for dev/test environments that use `Base.metadata.create_all()`
    instead of Alembic migrations.

    Safe to call multiple times.
    """

    # Import inside the function to avoid import cycles (models import DEFAULT_TENANT_ID).
    from baseliner_server.db.models import Tenant  # noqa: WPS433

    try:
        existing = db.get(Tenant, DEFAULT_TENANT_ID)
        if existing is not None:
            return
    except Exception:
        # If Session.get isn't supported for some reason, fall back to a cheap query.
        try:
            existing = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one_or_none()
            if existing is not None:
                return
        except Exception:
            pass

    db.add(
        Tenant(
            id=DEFAULT_TENANT_ID,
            name=DEFAULT_TENANT_NAME,
            created_at=utcnow(),
            is_active=True,
        )
    )

    # Best-effort: tolerate a concurrent creator.
    try:
        db.flush()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
