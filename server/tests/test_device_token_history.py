import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device, DeviceAuthToken, DeviceStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _create_device(db, *, device_key: str, token: str) -> Device:
    now = _utcnow()
    d = Device(
        device_key=device_key,
        hostname=f"host-{device_key}",
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


def _post_empty_report(client: TestClient, token: str):
    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
    }
    return client.post(
        "/api/v1/device/reports",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def _mint_enroll_token(client: TestClient) -> str:
    resp = client.post("/api/v1/admin/enroll-tokens", json={"ttl_seconds": 3600, "single_use": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["token"]


def test_reenroll_writes_history_and_revokes_previous_token(client, db):
    enroll_token = _mint_enroll_token(client)
    payload = {
        "enroll_token": enroll_token,
        "device_key": "REENROLL-1",
        "hostname": "reenroll-host",
        "os": "linux",
        "os_version": "1.0",
        "arch": "x64",
        "agent_version": "0.2.0",
        "tags": {"env": "test"},
    }

    r1 = client.post("/api/v1/enroll", json=payload)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    device_id = uuid.UUID(body1["device_id"])
    old_token = body1["device_token"]

    initial_rows = db.scalars(select(DeviceAuthToken).where(DeviceAuthToken.device_id == device_id)).all()
    assert len(initial_rows) == 1

    payload["enroll_token"] = _mint_enroll_token(client)
    r2 = client.post("/api/v1/enroll", json=payload)
    assert r2.status_code == 200, r2.text
    new_token = r2.json()["device_token"]
    new_hash = hash_token(new_token)

    db.expire_all()
    rows = db.scalars(
        select(DeviceAuthToken)
        .where(DeviceAuthToken.device_id == device_id)
        .order_by(DeviceAuthToken.created_at)
    ).all()
    assert len(rows) == 2

    old_row = next(r for r in rows if r.token_hash == hash_token(old_token))
    new_row = next(r for r in rows if r.token_hash == new_hash)
    assert old_row.revoked_at is not None
    assert old_row.replaced_by_id == new_row.id
    assert new_row.revoked_at is None

    assert _post_empty_report(client, old_token).status_code == 403
    assert _post_empty_report(client, new_token).status_code == 200


def test_delete_rotates_and_logs_history(client, db):
    old_token = "tok-history-delete"
    dev = _create_device(db, device_key="HIST-DEL", token=old_token)
    db.commit()

    resp = client.delete(f"/api/v1/admin/devices/{dev.id}?reason=cleanup")
    assert resp.status_code == 200, resp.text

    db.expire_all()
    rows = db.scalars(
        select(DeviceAuthToken)
        .where(DeviceAuthToken.device_id == dev.id)
        .order_by(DeviceAuthToken.created_at)
    ).all()
    assert len(rows) == 2
    legacy, rotated = rows
    assert legacy.token_hash == hash_token(old_token)
    assert legacy.revoked_at is not None
    assert legacy.replaced_by_id == rotated.id
    assert rotated.revoked_at is None


def test_restore_revokes_deleted_token_and_tracks_history(client, db):
    original_token = "tok-history-restore"
    dev = _create_device(db, device_key="HIST-RESTORE", token=original_token)
    db.commit()

    delete_resp = client.delete(f"/api/v1/admin/devices/{dev.id}")
    assert delete_resp.status_code == 200, delete_resp.text

    restore_resp = client.post(f"/api/v1/admin/devices/{dev.id}/restore")
    assert restore_resp.status_code == 200, restore_resp.text
    restored_token = restore_resp.json()["device_token"]

    db.expire_all()
    rows = db.scalars(
        select(DeviceAuthToken)
        .where(DeviceAuthToken.device_id == dev.id)
        .order_by(DeviceAuthToken.created_at)
    ).all()
    assert len(rows) == 3
    _, deleted_state_token, restored = rows
    assert deleted_state_token.revoked_at is not None
    assert deleted_state_token.replaced_by_id == restored.id
    assert restored.revoked_at is None

    assert _post_empty_report(client, original_token).status_code == 403
    assert _post_empty_report(client, restored_token).status_code == 200


def test_admin_revoke_writes_history_and_revokes(client, db):
    old_token = "tok-history-admin-revoke"
    dev = _create_device(db, device_key="HIST-ADMIN-REVOKE", token=old_token)
    db.commit()

    resp = client.post(f"/api/v1/admin/devices/{dev.id}/revoke-token")
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["device_token"]

    db.expire_all()
    rows = db.scalars(
        select(DeviceAuthToken)
        .where(DeviceAuthToken.device_id == dev.id)
        .order_by(DeviceAuthToken.created_at)
    ).all()
    assert len(rows) == 2
    legacy, rotated = rows
    assert legacy.token_hash == hash_token(old_token)
    assert legacy.revoked_at is not None
    assert legacy.replaced_by_id == rotated.id
    assert rotated.revoked_at is None

    assert _post_empty_report(client, old_token).status_code == 403
    assert _post_empty_report(client, new_token).status_code == 200
