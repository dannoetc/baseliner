from __future__ import annotations


def test_tenant_lifecycle_end_to_end(client):
    # 1) superadmin creates a tenant
    r = client.post("/api/v1/admin/tenants", json={"name": "acme", "is_active": True})
    assert r.status_code == 200, r.text
    tenant_id = r.json()["tenant"]["id"]

    # 2) superadmin issues a tenant_admin key for that tenant
    r = client.post(
        f"/api/v1/admin/tenants/{tenant_id}/admin-keys",
        json={"scope": "tenant_admin", "note": "test"},
    )
    assert r.status_code == 200, r.text
    issued = r.json()
    raw_key = issued["admin_key"]
    key_id = issued["key_id"]

    # 3) tenant_admin can access normal tenant-scoped admin endpoints
    tenant_headers = {"X-Admin-Key": raw_key, "X-Tenant-ID": tenant_id}
    r = client.get("/api/v1/admin/devices", headers=tenant_headers)
    assert r.status_code == 200, r.text
    assert r.json().get("total") == 0

    # 4) tenant_admin cannot create tenants (superadmin-only)
    r = client.post(
        "/api/v1/admin/tenants",
        json={"name": "nope"},
        headers=tenant_headers,
    )
    assert r.status_code == 403, r.text

    # 5) superadmin can revoke the issued admin key
    r = client.delete(f"/api/v1/admin/tenants/{tenant_id}/admin-keys/{key_id}")
    assert r.status_code == 204, r.text

    # Negative: revoked key no longer authenticates
    r = client.get("/api/v1/admin/devices", headers=tenant_headers)
    assert r.status_code == 401, r.text
