from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import and_, select
from sqlalchemy.sql import Select

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
      - admin key remains global (superadmin scope)

    Future:
      - admin keys can be scoped to a tenant
      - device auth tokens implicitly map to a tenant via the device row
    """

    id: uuid.UUID
    admin_scope: str = "superadmin"

    @property
    def is_superadmin(self) -> bool:
        return self.admin_scope == "superadmin"


def get_tenant_context() -> TenantContext:
    # FastAPI dependency (no args): returns the current tenant context.
    # Phase 0: single-tenant default with superadmin-scoped admin key.
    return TenantContext(id=DEFAULT_TENANT_ID, admin_scope="superadmin")


class TenantScopedSession:
    """Session wrapper that scopes queries to the current tenant."""

    def __init__(self, db: "Session", tenant: TenantContext):
        self.db = db
        self.tenant = tenant

    def _tenant_filters(self, entities: Iterable[object]):
        filters = []
        for ent in entities:
            model = getattr(ent, "entity", ent)
            tenant_col = getattr(model, "tenant_id", None)
            if tenant_col is not None:
                filters.append(tenant_col == self.tenant.id)
        return filters

    def _scope_select(self, stmt: Select) -> Select:
        tenant_filters = []
        for from_clause in stmt.get_final_froms():
            try:
                tenant_col = from_clause.c.tenant_id
            except Exception:
                continue
            tenant_filters.append(tenant_col == self.tenant.id)

        if tenant_filters:
            stmt = stmt.where(and_(*tenant_filters))
        return stmt

    def _maybe_scope_statement(self, stmt):
        if isinstance(stmt, Select):
            return self._scope_select(stmt)
        return stmt

    def query(self, *entities, **kwargs):
        q = self.db.query(*entities, **kwargs)
        tenant_filters = self._tenant_filters(entities)
        if tenant_filters:
            q = q.filter(*tenant_filters)
        return q

    def select(self, *entities):
        stmt = select(*entities)
        return self._scope_select(stmt)

    def scalar(self, stmt, **kwargs):
        scoped_stmt = self._maybe_scope_statement(stmt)
        return self.db.scalar(scoped_stmt, **kwargs)

    def execute(self, stmt, **kwargs):
        scoped_stmt = self._maybe_scope_statement(stmt)
        return self.db.execute(scoped_stmt, **kwargs)

    def get(self, entity, ident, **kwargs):
        obj = self.db.get(entity, ident, **kwargs)
        if obj is None:
            return None
        tenant_col = getattr(entity, "tenant_id", None)
        if tenant_col is None:
            return obj
        if getattr(obj, "tenant_id", None) != self.tenant.id:
            return None
        return obj

    def __getattr__(self, item):
        return getattr(self.db, item)


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
        return

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
