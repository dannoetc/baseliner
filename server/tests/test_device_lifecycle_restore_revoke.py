from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device, DeviceStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _find_route_path(client: TestClient, *, suffix: str, method: str) -> str:
    for r in getattr(client.app, "routes", []):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if (
            isinstance(path, str)
            and path.endswith(suffix)
            and methods
            and method.upper() in methods
        ):
            return path
    raise AssertionError(f"route not registered: {method} *{suffix}")


def _admin_delete_device_path(client: TestClient) -> str:
    return _find_route_path(client, suffix="/admin/devices/{device_id}", method="DELETE")


def _admin_restore_device_path(client: TestClient) -> str:
    return _find_route_path(client, suffix="/admin/devices/{device_id}/restore", method="POST")


def _admin_revoke_device_token_path(client: TestClient) -> str:
    return _find_route_path(client, suffix="/admin/devices/{device_id}/revoke-token", method="POST")


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


def test_restore_mints_new_token_and_allows_new_token(client, db):
    old_token = "tok-restore-old"
    dev = _create_device(db, device_key="RST1", token=old_token)
    db.commit()

    # Soft delete
    delete_path = _admin_delete_device_path(client).replace("{device_id}", str(dev.id))
    rdel = client.delete(delete_path)
    assert rdel.status_code == 200, rdel.text

    # Restore
    restore_path = _admin_restore_device_path(client).replace("{device_id}", str(dev.id))
    r = client.post(restore_path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] == str(dev.id)
    assert (body["status"] or "").lower() == "active"
    assert body.get("device_token")

    new_token = body["device_token"]

    # Old token should remain blocked with a clear 403.
    rr_old = _post_empty_report(client, old_token)
    assert rr_old.status_code == 403, rr_old.text

    # New token should work.
    rr_new = _post_empty_report(client, new_token)
    assert rr_new.status_code == 200, rr_new.text

    d2 = db.scalar(select(Device).where(Device.id == dev.id))
    assert d2 is not None
    assert d2.status == DeviceStatus.active
    assert d2.deleted_at is None


def test_restore_when_active_conflict(client, db):
    dev = _create_device(db, device_key="RST2", token="tok")
    db.commit()

    restore_path = _admin_restore_device_path(client).replace("{device_id}", str(dev.id))
    r = client.post(restore_path)
    assert r.status_code == 409, r.text


def test_revoke_token_rotates_and_new_token_works(client, db):
    old_token = "tok-revoke-old"
    dev = _create_device(db, device_key="RVK1", token=old_token)
    db.commit()

    revoke_path = _admin_revoke_device_token_path(client).replace("{device_id}", str(dev.id))
    r = client.post(revoke_path)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["device_id"] == str(dev.id)
    assert (body["status"] or "").lower() == "active"
    assert body.get("device_token")
    new_token = body["device_token"]

    rr_old = _post_empty_report(client, old_token)
    assert rr_old.status_code == 403, rr_old.text

    rr_new = _post_empty_report(client, new_token)
    assert rr_new.status_code == 200, rr_new.text


def test_revoke_token_on_deleted_conflict(client, db):
    dev = _create_device(db, device_key="RVK2", token="tok")
    db.commit()

    delete_path = _admin_delete_device_path(client).replace("{device_id}", str(dev.id))
    rdel = client.delete(delete_path)
    assert rdel.status_code == 200, rdel.text

    revoke_path = _admin_revoke_device_token_path(client).replace("{device_id}", str(dev.id))
    r = client.post(revoke_path)
    assert r.status_code == 409, r.text
