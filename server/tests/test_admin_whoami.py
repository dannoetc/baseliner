from __future__ import annotations

def test_admin_whoami_superadmin(client):
    r = client.get("/api/v1/admin/whoami")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("tenant_id")
    admin_key = data.get("admin_key") or {}
    assert admin_key.get("scope") == "superadmin"


def test_admin_whoami_tenant_admin(client):
    # 1) superadmin creates a tenant
    r = client.post("/api/v1/admin/tenants", json={"name": "acme-whoami", "is_active": True})
    assert r.status_code == 200, r.text
    tenant_id = r.json()["tenant"]["id"]

    # 2) superadmin issues a tenant_admin key for that tenant
    r = client.post(
        f"/api/v1/admin/tenants/{tenant_id}/admin-keys",
        json={"scope": "tenant_admin", "note": "whoami-test"},
    )
    assert r.status_code == 200, r.text
    issued = r.json()
    raw_key = issued["admin_key"]

    # 3) whoami reflects the tenant + scope
    headers = {"X-Admin-Key": raw_key, "X-Tenant-ID": tenant_id}
    r = client.get("/api/v1/admin/whoami", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("tenant_id") == tenant_id
    admin_key = data.get("admin_key") or {}
    assert admin_key.get("tenant_id") == tenant_id
    assert admin_key.get("scope") == "tenant_admin"
