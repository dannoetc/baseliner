from __future__ import annotations

from datetime import datetime, timedelta, timezone

from baseliner_server.db.models import (
    AssignmentMode,
    Device,
    Policy,
    PolicyAssignment,
    Run,
    RunItem,
    RunStatus,
    StepStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_device(db, *, device_key: str) -> Device:
    d = Device(
        device_key=device_key,
        hostname="host-" + device_key,
        os="windows",
        os_version="10.0",
        arch="x64",
        agent_version="0.1.0-dev",
        tags={"env": "test"},
        enrolled_at=utcnow(),
        last_seen_at=utcnow(),
        auth_token_hash="testhash",
    )
    db.add(d)
    db.flush()
    return d


def test_admin_device_debug_bundle_shape(client, db):
    """Debug bundle is the MVP operator workflow: it must be stable and complete."""

    d = _create_device(db, device_key="D-DEBUG")

    pol = Policy(
        name="debug-test-policy",
        description="",
        schema_version="1.0",
        is_active=True,
        document={
            "resources": [
                {
                    "type": "winget.package",
                    "package_id": "Mozilla.Firefox",
                    "ensure": "present",
                }
            ]
        },
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(pol)
    db.flush()

    a = PolicyAssignment(
        device_id=d.id,
        policy_id=pol.id,
        mode=AssignmentMode.enforce,
        priority=100,
        created_at=utcnow() - timedelta(minutes=1),
    )
    db.add(a)
    db.flush()

    run = Run(
        device_id=d.id,
        started_at=utcnow() - timedelta(seconds=20),
        ended_at=utcnow() - timedelta(seconds=5),
        effective_policy_hash="deadbeef",
        status=RunStatus.succeeded,
        agent_version="0.1.0-dev",
        policy_snapshot={"policy_name": "debug-test-policy"},
        summary={"items_total": 1, "items_failed": 0, "items_changed": 0},
    )
    db.add(run)
    db.flush()

    ri = RunItem(
        run_id=run.id,
        resource_type="winget.package",
        resource_id="mozilla.firefox",
        name="Firefox",
        ordinal=0,
        compliant_before=False,
        compliant_after=True,
        changed=False,
        reboot_required=False,
        status_detect=StepStatus.ok,
        status_remediate=StepStatus.ok,
        status_validate=StepStatus.ok,
        evidence={"validate": {"installed": True}},
        error={},
    )
    db.add(ri)
    db.commit()

    r = client.get(f"/api/v1/admin/devices/{d.id}/debug")
    assert r.status_code == 200
    j = r.json()

    assert j["device"]["id"] == str(d.id)
    assert j["device"]["device_key"] == "D-DEBUG"

    # assignments ordered + include policy name
    assert isinstance(j.get("assignments"), list)
    assert len(j["assignments"]) == 1
    assert j["assignments"][0]["policy_name"] == "debug-test-policy"

    # effective policy contains compiled doc + compile metadata
    ep = j.get("effective_policy")
    assert isinstance(ep, dict)
    assert ep.get("effective_policy_hash")
    assert isinstance((ep.get("document") or {}).get("resources"), list)
    assert (ep.get("compile") or {}).get("assignments") is not None

    # last run included + items included
    lr = j.get("last_run")
    assert isinstance(lr, dict)
    assert lr.get("id") == str(run.id)
    assert lr.get("status") in ("succeeded", "failed", "running", "partial", None)

    items = j.get("last_run_items")
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["resource_type"] == "winget.package"
