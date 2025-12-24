from __future__ import annotations

import uuid
from datetime import datetime, timezone

from baseliner_server.api.deps import hash_token
from baseliner_server.core.tenancy import (
    DEFAULT_TENANT_ID,
    TenantContext,
    TenantScopedSession,
    ensure_default_tenant,
    get_tenant_context,
)
from baseliner_server.db.models import Device, EnrollToken, Tenant
from baseliner_server.main import app


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_scoped_session_filters_cross_tenant_rows(db):
    ensure_default_tenant(db)
    other_tenant = Tenant(id=uuid.uuid4(), name="other", created_at=utcnow(), is_active=True)
    db.add(other_tenant)
    db.flush()

    foreign_token = EnrollToken(tenant_id=other_tenant.id, token_hash="other-hash", created_at=utcnow())
    db.add(foreign_token)
    db.commit()

    scoped = TenantScopedSession(db, get_tenant_context())

    # Default tenant context should not see rows from other tenants.
    assert scoped.get(EnrollToken, foreign_token.id) is None
    assert scoped.query(EnrollToken).count() == 0


def test_enroll_token_listing_respects_tenant_context(client, db):
    ensure_default_tenant(db)
    other_tenant = Tenant(id=uuid.uuid4(), name="other", created_at=utcnow(), is_active=True)
    db.add(other_tenant)
    db.flush()

    db.add(
        EnrollToken(
            tenant_id=DEFAULT_TENANT_ID,
            token_hash="default-hash",
            created_at=utcnow(),
            note="default",
        )
    )
    db.add(
        EnrollToken(
            tenant_id=other_tenant.id,
            token_hash="other-hash",
            created_at=utcnow(),
            note="other",
        )
    )
    db.commit()

    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        id=other_tenant.id, admin_scope="tenant"
    )
    try:
        resp = client.get("/api/v1/admin/enroll-tokens")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["note"] == "other"
    finally:
        app.dependency_overrides.pop(get_tenant_context, None)


def test_cross_tenant_device_debug_forbidden(client, db):
    ensure_default_tenant(db)
    other_tenant = Tenant(id=uuid.uuid4(), name="other", created_at=utcnow(), is_active=True)
    db.add(other_tenant)
    db.flush()

    device = Device(
        tenant_id=other_tenant.id,
        device_key="CROSS-TENANT",
        hostname="cross-host",
        enrolled_at=utcnow(),
        last_seen_at=utcnow(),
        auth_token_hash=hash_token("secret"),
    )
    db.add(device)
    db.commit()

    resp = client.get(f"/api/v1/admin/devices/{device.id}/debug")
    assert resp.status_code == 404, resp.text
