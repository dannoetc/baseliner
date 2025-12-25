from __future__ import annotations


def test_admin_whoami_superadmin(client):
    r = client.get("/api/v1/admin/whoami")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("tenant_id")
    admin_key = data.get("admin_key") or {}
    # superadmin bootstrap key should report superadmin
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

    # 3) whoami reflects effective tenant + scope (X-Tenant-ID optional)
    headers = {"X-Admin-Key": raw_key}
    r = client.get("/api/v1/admin/whoami", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("tenant_id") == tenant_id
    assert data.get("effective_tenant_id") == tenant_id
    assert data.get("requested_tenant_id") is None
    assert data.get("tenant_mismatch") is False

    ak = data.get("admin_key") or {}
    assert ak.get("tenant_id") == tenant_id
    assert ak.get("scope") == "tenant_admin"

    # 4) if a mismatched X-Tenant-ID is provided, the effective tenant is still the key's tenant
    other_tenant = "00000000-0000-0000-0000-000000000001"
    headers = {"X-Admin-Key": raw_key, "X-Tenant-ID": other_tenant}
    r = client.get("/api/v1/admin/whoami", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("requested_tenant_id") == other_tenant
    assert data.get("effective_tenant_id") == tenant_id
    assert data.get("tenant_mismatch") is True
