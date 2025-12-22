from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import (
    AssignmentMode,
    Device,
    DeviceStatus,
    Policy,
    PolicyAssignment,
)


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


def _admin_list_devices_path(client: TestClient) -> str:
    return _find_route_path(client, suffix="/admin/devices", method="GET")


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


def _create_policy(db, *, name: str = "p1") -> Policy:
    now = _utcnow()
    p = Policy(
        name=name,
        description="test",
        schema_version="1",
        document={"schema_version": "1", "resources": []},
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    db.flush()
    return p


def _assign_policy(db, *, device_id, policy_id) -> PolicyAssignment:
    a = PolicyAssignment(
        device_id=device_id,
        policy_id=policy_id,
        mode=AssignmentMode.enforce,
        priority=100,
        created_at=_utcnow(),
    )
    db.add(a)
    db.flush()
    return a


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


def test_soft_delete_revokes_and_blocks_device_token(client, db):
    token = "tok-delete"
    dev = _create_device(db, device_key="DEL1", token=token)
    pol = _create_policy(db, name="pol1")
    _assign_policy(db, device_id=dev.id, policy_id=pol.id)
    db.commit()

    delete_path = _admin_delete_device_path(client).replace("{device_id}", str(dev.id))
    r = client.delete(f"{delete_path}?reason=testing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] == str(dev.id)
    assert (body["status"] or "").lower() == "deleted"
    assert body["assignments_removed"] == 1

    # Agent token should now be blocked with a clear 403 (not 401).
    rr = _post_empty_report(client, token)
    assert rr.status_code == 403, rr.text

    # Ensure DB reflects deletion.
    d2 = db.scalar(select(Device).where(Device.id == dev.id))
    assert d2 is not None
    assert d2.status == DeviceStatus.deleted
    assert d2.deleted_at is not None
    assert d2.token_revoked_at is not None
    assert d2.revoked_auth_token_hash is not None


def test_soft_delete_idempotent_does_not_break_revoked_token_mapping(client, db):
    token = "tok-idem"
    dev = _create_device(db, device_key="DEL2", token=token)
    db.commit()

    delete_path = _admin_delete_device_path(client).replace("{device_id}", str(dev.id))
    r1 = client.delete(delete_path)
    assert r1.status_code == 200, r1.text

    r2 = client.delete(delete_path)
    assert r2.status_code == 200, r2.text

    # Still a clear 403, meaning the revoked hash mapping was preserved.
    rr = _post_empty_report(client, token)
    assert rr.status_code == 403, rr.text


def test_list_devices_excludes_deleted_by_default(client, db):
    _create_device(db, device_key="ACTIVE1", token="a1")
    dev_b = _create_device(db, device_key="ACTIVE2", token="a2")
    db.commit()

    delete_path = _admin_delete_device_path(client).replace("{device_id}", str(dev_b.id))
    rdel = client.delete(delete_path)
    assert rdel.status_code == 200, rdel.text

    list_path = _admin_list_devices_path(client)
    r = client.get(f"{list_path}?include_health=false")
    assert r.status_code == 200, r.text
    keys = [x["device_key"] for x in r.json()["items"]]
    assert "ACTIVE1" in keys
    assert "ACTIVE2" not in keys

    r2 = client.get(f"{list_path}?include_health=false&include_deleted=true")
    assert r2.status_code == 200, r2.text
    keys2 = [x["device_key"] for x in r2.json()["items"]]
    assert "ACTIVE2" in keys2
