from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from baseliner_server.services.policy_compiler import compile_effective_policy
from baseliner_server.db.models import AssignmentMode, Device, Policy, PolicyAssignment


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


def _create_policy(db, *, name: str, resource_name: str) -> Policy:
    # Same resource key across policies (type + id), but with a distinguishing field ("name")
    p = Policy(
        name=name,
        description="",
        schema_version="1.0",
        is_active=True,
        document={
            "resources": [
                {
                    "type": "winget.package",
                    "id": "mozilla.firefox",           # ensure same resource key across policies
                    "package_id": "Mozilla.Firefox",
                    "ensure": "present",
                    "name": resource_name,            # distinguish winner
                }
            ]
        },
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(p)
    db.flush()
    return p


def _assign(
    db,
    *,
    device_id: uuid.UUID,
    policy_id: uuid.UUID,
    priority: int,
    created_at: datetime,
    assignment_id: uuid.UUID | None = None,
) -> PolicyAssignment:
    a = PolicyAssignment(
        id=assignment_id or uuid.uuid4(),
        device_id=device_id,
        policy_id=policy_id,
        mode=AssignmentMode.enforce,
        priority=priority,
        created_at=created_at,
    )
    db.add(a)
    db.flush()
    return a


def _compiled_first_resource_name(snap) -> str:
    doc = snap.policy or {}
    res = (doc.get("resources") or [])
    assert isinstance(res, list) and res, "compiled policy has no resources"
    first = res[0]
    assert isinstance(first, dict)
    return str(first.get("name") or "")


def test_compiler_priority_lower_number_wins(db):
    """Lower priority number should win (priority ASC)."""
    d = _create_device(db, device_key="D-DET-PRIO")
    p_a = _create_policy(db, name="pol-a", resource_name="FROM-A")
    p_b = _create_policy(db, name="pol-b", resource_name="FROM-B")

    t = utcnow()
    _assign(db, device_id=d.id, policy_id=p_a.id, priority=100, created_at=t)
    _assign(db, device_id=d.id, policy_id=p_b.id, priority=200, created_at=t + timedelta(seconds=1))
    db.commit()

    snap = compile_effective_policy(db, d)
    assert _compiled_first_resource_name(snap) == "FROM-A"

    compile_meta = (snap.meta or {}).get("compile") or {}
    # conflicts should include at least one entry
    conflicts = compile_meta.get("conflicts") or []
    assert isinstance(conflicts, list)
    assert len(conflicts) >= 1


def test_compiler_created_at_tiebreaker_earlier_wins(db):
    """If priorities tie, earlier assignment.created_at wins."""
    d = _create_device(db, device_key="D-DET-CT")
    p_a = _create_policy(db, name="pol-a", resource_name="FROM-A")
    p_b = _create_policy(db, name="pol-b", resource_name="FROM-B")

    t = utcnow()
    _assign(db, device_id=d.id, policy_id=p_a.id, priority=100, created_at=t)
    _assign(db, device_id=d.id, policy_id=p_b.id, priority=100, created_at=t + timedelta(seconds=5))
    db.commit()

    snap = compile_effective_policy(db, d)
    assert _compiled_first_resource_name(snap) == "FROM-A"

    compile_meta = (snap.meta or {}).get("compile") or {}
    assigns = compile_meta.get("assignments") or []
    assert isinstance(assigns, list)
    # First assignment in compile list should be pol-a
    assert assigns[0].get("policy_name") in ("pol-a", "pol-a")  # tolerate exact key naming


def test_compiler_assignment_id_tiebreaker_lower_uuid_wins(db):
    """If priority + created_at tie, assignment_id ASC should win."""
    d = _create_device(db, device_key="D-DET-ID")
    p_a = _create_policy(db, name="pol-a", resource_name="FROM-A")
    p_b = _create_policy(db, name="pol-b", resource_name="FROM-B")

    t = utcnow()

    low_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    _assign(db, device_id=d.id, policy_id=p_a.id, priority=100, created_at=t, assignment_id=low_id)
    _assign(db, device_id=d.id, policy_id=p_b.id, priority=100, created_at=t, assignment_id=high_id)
    db.commit()

    snap = compile_effective_policy(db, d)
    assert _compiled_first_resource_name(snap) == "FROM-A"

    compile_meta = (snap.meta or {}).get("compile") or {}
    conflicts = compile_meta.get("conflicts") or []
    assert isinstance(conflicts, list)
    assert len(conflicts) >= 1
    # If you store a 'reason' string, this helps ensure we don't regress ordering semantics.
    # (Skip hard assertion if not present.)
    if conflicts and isinstance(conflicts[0], dict) and "reason" in conflicts[0]:
        assert "first-wins" in str(conflicts[0]["reason"]).lower()
