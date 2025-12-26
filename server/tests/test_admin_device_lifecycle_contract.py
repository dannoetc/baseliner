from datetime import datetime, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_admin_key
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID
from baseliner_server.db.models import AdminKey, AdminScope, AuditLog, Device, DeviceStatus, Tenant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_tenant(db, *, name: str, admin_key: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name=name, created_at=_utcnow(), is_active=True)
    db.add(tenant)
    db.add(
        AdminKey(
            tenant_id=tenant.id,
            key_hash=hash_admin_key(admin_key),
            scope=AdminScope.tenant_admin,
            note=name,
        )
    )
    db.commit()
    return tenant


def _device_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Admin-Key": "", "X-Tenant-ID": ""}


def _enroll_device(client: TestClient, *, headers: dict[str, str], device_key: str) -> dict:
    enroll = client.post("/api/v1/admin/enroll-tokens", headers=headers, json={})
    assert enroll.status_code == 200, enroll.text
    tok = enroll.json()["token"]

    payload = {
        "enroll_token": tok,
        "device_key": device_key,
        "hostname": device_key,
        "os": "windows",
        "arch": "x64",
        "agent_version": "1.0.0",
        "tags": {},
    }
    dev = client.post("/api/v1/enroll", json=payload)
    assert dev.status_code == 200, dev.text
    return dev.json()


def test_tenant_admin_deactivate_blocks_device(client: TestClient, db) -> None:
    tenant = _make_tenant(db, name="tenant-deact", admin_key="tenant-deact-key")
    headers = {"X-Admin-Key": "tenant-deact-key", "X-Tenant-ID": str(tenant.id)}

    device = _enroll_device(client, headers=headers, device_key="DEACT100")
    device_headers = _device_headers(device["device_token"])

    ok = client.get("/api/v1/device/policy", headers=device_headers)
    assert ok.status_code == 200, ok.text

    resp = client.post(f"/api/v1/admin/devices/{device['device_id']}/deactivate", headers=headers, json={"reason": "offboard"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body.get("status") or "").lower() == DeviceStatus.deactivated.value
    assert body.get("revoked_tokens") is True

    blocked = client.get("/api/v1/device/policy", headers=device_headers)
    assert blocked.status_code == 403, blocked.text
    assert "deactivated" in blocked.text.lower()

    db.expire_all()
    d_row = db.scalar(select(Device).where(Device.id == uuid.UUID(device["device_id"])))
    assert d_row is not None
    assert d_row.status == DeviceStatus.deactivated

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "device.deactivate"))
    assert audit is not None
    assert audit.tenant_id == tenant.id
    assert audit.target_id == device["device_id"]


def test_rotate_token_blocks_old_allows_new(client: TestClient, db) -> None:
    headers = {"X-Admin-Key": "", "X-Tenant-ID": str(DEFAULT_TENANT_ID)}
    device = _enroll_device(client, headers=headers, device_key="ROTATION1")
    old_token = device["device_token"]
    device_headers = _device_headers(old_token)

    rotate = client.post(f"/api/v1/admin/devices/{device['device_id']}/rotate-token")
    assert rotate.status_code == 200, rotate.text
    rotated_body = rotate.json()
    assert rotated_body.get("token")
    new_token = rotated_body["token"]

    blocked = client.get("/api/v1/device/policy", headers=device_headers)
    assert blocked.status_code == 403, blocked.text

    new_ok = client.get("/api/v1/device/policy", headers=_device_headers(new_token))
    assert new_ok.status_code == 200, new_ok.text

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "device.rotate_token"))
    assert audit is not None
    assert audit.target_id == device["device_id"]


def test_tenant_admin_cannot_target_other_tenant_device(client: TestClient, db) -> None:
    tenant_one = _make_tenant(db, name="tenant-one", admin_key="tenant-one-key")
    tenant_two = _make_tenant(db, name="tenant-two", admin_key="tenant-two-key")

    headers_two = {"X-Admin-Key": "tenant-two-key", "X-Tenant-ID": str(tenant_two.id)}
    device = _enroll_device(client, headers=headers_two, device_key="ISOLATE1")

    headers_one = {"X-Admin-Key": "tenant-one-key", "X-Tenant-ID": str(tenant_one.id)}
    resp = client.post(f"/api/v1/admin/devices/{device['device_id']}/deactivate", headers=headers_one)
    assert resp.status_code in (403, 404)

    rotate = client.post(f"/api/v1/admin/devices/{device['device_id']}/rotate-token", headers=headers_one)
    assert rotate.status_code in (403, 404)


def test_reactivate_keeps_token_revocation_until_rotated(client: TestClient, db) -> None:
    tenant = _make_tenant(db, name="tenant-react", admin_key="tenant-react-key")
    headers = {"X-Admin-Key": "tenant-react-key", "X-Tenant-ID": str(tenant.id)}
    device = _enroll_device(client, headers=headers, device_key="REACTDEV1")
    device_headers = _device_headers(device["device_token"])

    deactivate = client.post(f"/api/v1/admin/devices/{device['device_id']}/deactivate", headers=headers)
    assert deactivate.status_code == 200, deactivate.text

    reactivate = client.post(f"/api/v1/admin/devices/{device['device_id']}/reactivate", headers=headers)
    assert reactivate.status_code == 200, reactivate.text
    body = reactivate.json()
    assert (body.get("status") or "").lower() == DeviceStatus.active.value

    blocked = client.get("/api/v1/device/policy", headers=device_headers)
    assert blocked.status_code == 403

    rotate = client.post(f"/api/v1/admin/devices/{device['device_id']}/rotate-token", headers=headers)
    assert rotate.status_code == 200, rotate.text
    new_token = rotate.json()["token"]

    new_ok = client.get("/api/v1/device/policy", headers=_device_headers(new_token))
    assert new_ok.status_code == 200, new_ok.text

    audits = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.target_id == device["device_id"],
                AuditLog.action.in_(
                    ["device.deactivate", "device.reactivate", "device.rotate_token"]
                ),
            )
        ).all()
    )
    assert {a.action for a in audits} == {
        "device.deactivate",
        "device.reactivate",
        "device.rotate_token",
    }
    assert all(a.tenant_id == tenant.id for a in audits)
