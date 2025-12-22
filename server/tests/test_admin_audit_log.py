from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device, DeviceStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _create_device(db, *, device_key: str, token: str) -> Device:
    now = _utcnow()
    d = Device(
        device_key=device_key,
        hostname="host-" + device_key,
        os="windows",
        os_version="10.0",
        arch="x64",
        agent_version="0.1.0-dev",
        tags={"env": "test"},
        enrolled_at=now,
        last_seen_at=now,
        auth_token_hash=hash_token(token),
        status=DeviceStatus.active,
    )
    db.add(d)
    db.flush()
    return d


def test_audit_logs_enroll_token_create(client: TestClient):
    r = client.post("/api/v1/admin/enroll-tokens", json={})
    assert r.status_code == 200, r.text

    ra = client.get("/api/v1/admin/audit")
    assert ra.status_code == 200, ra.text
    body = ra.json()
    assert body["items"], body

    ev = body["items"][0]
    assert ev["action"] == "enroll_token.create"
    assert ev["actor_type"] == "admin_key"
    assert ev["actor_id"] == "test-admin"
    assert ev["target_type"] == "enroll_token"
    assert ev["target_id"]


def test_audit_logs_device_delete_includes_reason(client: TestClient, db):
    dev = _create_device(db, device_key="AUDDEL1", token="tok-aud")
    db.commit()

    r = client.delete(f"/api/v1/admin/devices/{dev.id}?reason=testing")
    assert r.status_code == 200, r.text

    ra = client.get("/api/v1/admin/audit?action=device.delete")
    assert ra.status_code == 200, ra.text
    items = ra.json()["items"]
    assert len(items) == 1

    ev = items[0]
    assert ev["action"] == "device.delete"
    assert ev["target_type"] == "device"
    assert ev["target_id"] == str(dev.id)
    assert ev["data"]["reason"] == "testing"

    # Confirm device is deleted at DB layer too
    d2 = db.scalar(select(Device).where(Device.id == dev.id))
    assert d2 is not None
    assert d2.status == DeviceStatus.deleted


def test_audit_cursor_pagination(client: TestClient):
    # Generate 5 audit events
    for _ in range(5):
        r = client.post("/api/v1/admin/enroll-tokens", json={})
        assert r.status_code == 200

    r1 = client.get("/api/v1/admin/audit?limit=2")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert len(b1["items"]) == 2
    assert b1["next_cursor"], b1

    r2 = client.get(f"/api/v1/admin/audit?limit=2&cursor={b1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert len(b2["items"]) == 2

    ids1 = {x["id"] for x in b1["items"]}
    ids2 = {x["id"] for x in b2["items"]}
    assert ids1.isdisjoint(ids2)
