from __future__ import annotations

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import (
    AssignmentMode,
    AuditLog,
    Device,
    Policy,
    PolicyAssignment,
)


def test_admin_remove_single_assignment(client, db):
    device = Device(device_key="DEV-1", auth_token_hash=hash_token("tok-1"))
    policy = Policy(
        name="policy-1",
        schema_version="1.0",
        document={"schema_version": "1", "resources": []},
        is_active=True,
    )
    db.add(device)
    db.add(policy)
    db.flush()

    db.add(
        PolicyAssignment(
            device_id=device.id,
            policy_id=policy.id,
            priority=123,
            mode=AssignmentMode.enforce,
        )
    )
    db.commit()

    # Sanity: assignment exists.
    resp = client.get(f"/api/v1/admin/devices/{device.id}/assignments")
    assert resp.status_code == 200
    assert len(resp.json().get("assignments") or []) == 1

    # Remove it.
    resp = client.delete(f"/api/v1/admin/devices/{device.id}/assignments/{policy.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["device_id"] == str(device.id)
    assert body["policy_id"] == str(policy.id)
    assert body["removed"] == 1

    # Now none remain.
    resp = client.get(f"/api/v1/admin/devices/{device.id}/assignments")
    assert resp.status_code == 200
    assert len(resp.json().get("assignments") or []) == 0

    # Audit log emitted.
    db.expire_all()
    logs = list(db.query(AuditLog).filter(AuditLog.action == "assignment.remove").all())
    assert len(logs) >= 1


def test_admin_remove_assignment_missing_is_ok(client, db):
    device = Device(device_key="DEV-2", auth_token_hash=hash_token("tok-2"))
    policy = Policy(
        name="policy-2",
        schema_version="1.0",
        document={"schema_version": "1", "resources": []},
        is_active=True,
    )
    db.add(device)
    db.add(policy)
    db.commit()

    # Removing a non-existent assignment is idempotent.
    resp = client.delete(f"/api/v1/admin/devices/{device.id}/assignments/{policy.id}")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 0
