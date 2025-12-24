import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_admin_key
from baseliner_server.core.config import settings
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID
from baseliner_server.db.models import AdminKey, AdminScope, Device, EnrollToken, Run, Tenant


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


def _make_report_payload() -> dict:
    return {
        "started_at": _utcnow().isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
    }


def test_two_tenants_isolated_end_to_end(client: TestClient, db):
    tenant_b = Tenant(id=uuid.uuid4(), name="tenant-b", created_at=_utcnow(), is_active=True)
    db.add(tenant_b)
    db.add(
        AdminKey(
            tenant_id=tenant_b.id,
            key_hash=hash_admin_key("tenant-b-admin"),
            scope=AdminScope.tenant_admin,
            note="tenant-b",
        )
    )
    db.flush()
    db.commit()

    headers_a = {"X-Admin-Key": settings.baseliner_admin_key, "X-Tenant-ID": str(DEFAULT_TENANT_ID)}
    headers_b = {"X-Admin-Key": "tenant-b-admin", "X-Tenant-ID": str(tenant_b.id)}

    tok_a = client.post("/api/v1/admin/enroll-tokens", headers=headers_a, json={})
    tok_b = client.post("/api/v1/admin/enroll-tokens", headers=headers_b, json={})
    assert tok_a.status_code == 200, tok_a.text
    assert tok_b.status_code == 200, tok_b.text

    tok_b_row = db.get(EnrollToken, uuid.UUID(tok_b.json()["token_id"]))
    assert tok_b_row is not None
    assert tok_b_row.tenant_id == tenant_b.id

    enroll_a = client.post("/api/v1/enroll", json=_make_enroll_payload(tok_a.json()["token"], device_key="TENANT-A"))
    enroll_b = client.post("/api/v1/enroll", json=_make_enroll_payload(tok_b.json()["token"], device_key="TENANT-B"))
    assert enroll_a.status_code == 200, enroll_a.text
    assert enroll_b.status_code == 200, enroll_b.text

    device_a = enroll_a.json()
    device_b = enroll_b.json()

    db.expire_all()
    device_b_row = db.get(Device, uuid.UUID(device_b["device_id"]))
    assert device_b_row is not None
    assert device_b_row.tenant_id == tenant_b.id

    pol_a = client.post("/api/v1/admin/policies", headers=headers_a, json=_make_policy_payload("policy-a"))
    pol_b = client.post("/api/v1/admin/policies", headers=headers_b, json=_make_policy_payload("policy-b"))
    assert pol_a.status_code == 200, pol_a.text
    assert pol_b.status_code == 200, pol_b.text

    assign_a = client.post(
        "/api/v1/admin/assign-policy",
        headers=headers_a,
        json={
            "device_id": device_a["device_id"],
            "policy_name": "policy-a",
            "priority": 10,
            "mode": "enforce",
        },
    )
    assign_b = client.post(
        "/api/v1/admin/assign-policy",
        headers=headers_b,
        json={
            "device_id": device_b["device_id"],
            "policy_name": "policy-b",
            "priority": 10,
            "mode": "enforce",
        },
    )
    assert assign_a.status_code == 200, assign_a.text
    assert assign_b.status_code == 200, assign_b.text

    rep_a = client.post(
        "/api/v1/device/reports",
        headers={"Authorization": f"Bearer {device_a['device_token']}"},
        json=_make_report_payload(),
    )
    rep_b = client.post(
        "/api/v1/device/reports",
        headers={"Authorization": f"Bearer {device_b['device_token']}"},
        json=_make_report_payload(),
    )
    assert rep_a.status_code == 200, rep_a.text
    assert rep_b.status_code == 200, rep_b.text

    runs_a = list(db.scalars(select(Run).where(Run.tenant_id == DEFAULT_TENANT_ID)).all())
    runs_b = list(db.scalars(select(Run).where(Run.tenant_id == tenant_b.id)).all())
    assert len(runs_a) == 1
    assert len(runs_b) == 1

    list_a = client.get("/api/v1/admin/devices", headers=headers_a)
    list_b = client.get("/api/v1/admin/devices", headers=headers_b)
    assert list_a.status_code == 200, list_a.text
    assert list_b.status_code == 200, list_b.text

    devices_a = [d["device_key"] for d in list_a.json()["items"]]
    devices_b = [d["device_key"] for d in list_b.json()["items"]]
    assert "TENANT-A" in devices_a
    assert "TENANT-B" not in devices_a
    assert "TENANT-B" in devices_b
    assert "TENANT-A" not in devices_b

    cross_run = db.scalar(select(Run).where(Run.tenant_id == tenant_b.id, Run.device_id == uuid.UUID(device_a["device_id"])))
    assert cross_run is None
