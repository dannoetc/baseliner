import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.api.deps import hash_admin_key
from baseliner_server.core.config import settings
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID
from baseliner_server.db.models import AdminKey, AdminScope, Device, Policy, Tenant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_enroll_payload(token: str, *, device_key: str) -> dict:
    return {
        "enroll_token": token,
        "device_key": device_key,
        "hostname": f"host-{device_key}",
        "os": "windows",
        "arch": "x64",
        "agent_version": "1.0.0",
        "tags": {},
    }


def _make_policy_payload(name: str) -> dict:
    return {
        "name": name,
        "description": name,
        "schema_version": "1.0",
        "document": {"schema_version": "1", "resources": []},
        "is_active": True,
    }


def test_tenant_scoped_uniques_allow_collisions(client: TestClient, db: Session):
    tenant_b = Tenant(id=uuid.uuid4(), name="tenant-b-unique", created_at=_utcnow(), is_active=True)
    db.add(tenant_b)

    tenant_b_admin_key = "tenant-b-admin"
    db.add(
        AdminKey(
            tenant_id=tenant_b.id,
            key_hash=hash_admin_key(tenant_b_admin_key),
            scope=AdminScope.tenant_admin,
            note="tenant-b",
        )
    )

    collision_hash = hash_admin_key("shared-admin-key")
    db.add(
        AdminKey(
            tenant_id=DEFAULT_TENANT_ID,
            key_hash=collision_hash,
            scope=AdminScope.tenant_admin,
            note="default-collision",
        )
    )
    db.add(
        AdminKey(
            tenant_id=tenant_b.id,
            key_hash=collision_hash,
            scope=AdminScope.tenant_admin,
            note="tenant-b-collision",
        )
    )
    db.commit()

    headers_a = {"X-Admin-Key": settings.baseliner_admin_key, "X-Tenant-ID": str(DEFAULT_TENANT_ID)}
    headers_b = {"X-Admin-Key": tenant_b_admin_key, "X-Tenant-ID": str(tenant_b.id)}

    tok_a = client.post("/api/v1/admin/enroll-tokens", headers=headers_a, json={})
    tok_b = client.post("/api/v1/admin/enroll-tokens", headers=headers_b, json={})
    assert tok_a.status_code == 200, tok_a.text
    assert tok_b.status_code == 200, tok_b.text

    device_key = "DUP-DEVICE"
    enroll_a = client.post("/api/v1/enroll", json=_make_enroll_payload(tok_a.json()["token"], device_key=device_key))
    enroll_b = client.post("/api/v1/enroll", json=_make_enroll_payload(tok_b.json()["token"], device_key=device_key))
    assert enroll_a.status_code == 200, enroll_a.text
    assert enroll_b.status_code == 200, enroll_b.text

    policy_name = "baseline"
    pol_a = client.post("/api/v1/admin/policies", headers=headers_a, json=_make_policy_payload(policy_name))
    pol_b = client.post("/api/v1/admin/policies", headers=headers_b, json=_make_policy_payload(policy_name))
    assert pol_a.status_code == 200, pol_a.text
    assert pol_b.status_code == 200, pol_b.text

    admin_key_collisions = list(
        db.scalars(select(AdminKey).where(AdminKey.key_hash == collision_hash).order_by(AdminKey.tenant_id)).all()
    )
    assert len(admin_key_collisions) == 2
    assert admin_key_collisions[0].tenant_id != admin_key_collisions[1].tenant_id

    list_devices_a = client.get("/api/v1/admin/devices", headers=headers_a)
    list_devices_b = client.get("/api/v1/admin/devices", headers=headers_b)
    assert list_devices_a.status_code == 200, list_devices_a.text
    assert list_devices_b.status_code == 200, list_devices_b.text

    devices_a = list_devices_a.json()["items"]
    devices_b = list_devices_b.json()["items"]
    assert len(devices_a) == 1
    assert len(devices_b) == 1
    assert devices_a[0]["device_key"] == device_key
    assert devices_b[0]["device_key"] == device_key

    list_policies_a = client.get("/api/v1/admin/policies", headers=headers_a)
    list_policies_b = client.get("/api/v1/admin/policies", headers=headers_b)
    assert list_policies_a.status_code == 200, list_policies_a.text
    assert list_policies_b.status_code == 200, list_policies_b.text

    names_a = list_policies_a.json()["items"]
    names_b = list_policies_b.json()["items"]
    assert [p["name"] for p in names_a] == [policy_name]
    assert [p["name"] for p in names_b] == [policy_name]

    db.refresh(db.get(Device, uuid.UUID(enroll_a.json()["device_id"])))
    db.refresh(db.get(Device, uuid.UUID(enroll_b.json()["device_id"])))

    policy_ids = [uuid.UUID(pol_a.json()["policy_id"]), uuid.UUID(pol_b.json()["policy_id"])]
    refreshed_policies = list(db.scalars(select(Policy).where(Policy.id.in_(policy_ids))).all())
    assert {p.tenant_id for p in refreshed_policies} == {DEFAULT_TENANT_ID, tenant_b.id}

