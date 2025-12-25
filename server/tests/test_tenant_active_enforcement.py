import uuid
from datetime import datetime, timezone

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device


def test_inactive_tenant_blocks_tenant_admin_and_devices(client, db):
    # 1) Create an active tenant and a tenant_admin key
    r = client.post("/api/v1/admin/tenants", json={"name": "inactive-test", "is_active": True})
    assert r.status_code == 200, r.text
    tenant_id = r.json()["tenant"]["id"]

    r = client.post(
        f"/api/v1/admin/tenants/{tenant_id}/admin-keys",
        json={"scope": "tenant_admin", "note": "inactive-test"},
    )
    assert r.status_code == 200, r.text
    raw_key = r.json()["admin_key"]

    tenant_headers = {"X-Admin-Key": raw_key, "X-Tenant-ID": tenant_id}

    # Sanity: tenant_admin works while tenant is active
    r = client.get("/api/v1/admin/devices", headers=tenant_headers)
    assert r.status_code == 200, r.text

    # 2) Create a device under that tenant (for device-scope enforcement)
    token = "device-token-for-inactive-test"
    dev = Device(
        tenant_id=uuid.UUID(tenant_id),
        device_key="INACTIVE-TEST-DEVICE",
        auth_token_hash=hash_token(token),
        enrolled_at=datetime.now(timezone.utc),
        tags={},
    )
    db.add(dev)
    db.commit()

    device_headers = {
        "Authorization": f"Bearer {token}",
        # Override the default superadmin headers injected by the client fixture.
        "X-Admin-Key": "",
        "X-Tenant-ID": "",
    }

    r = client.get("/api/v1/device/policy", headers=device_headers)
    assert r.status_code == 200, r.text

    # 3) Deactivate the tenant (superadmin-only)
    r = client.patch(f"/api/v1/admin/tenants/{tenant_id}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["tenant"]["is_active"] is False

    # 4) tenant_admin is blocked
    r = client.get("/api/v1/admin/devices", headers=tenant_headers)
    assert r.status_code == 403, r.text
    assert "Tenant disabled" in r.text

    # 5) device requests are blocked
    r = client.get("/api/v1/device/policy", headers=device_headers)
    assert r.status_code == 403, r.text
    assert "Tenant disabled" in r.text
