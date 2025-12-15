from __future__ import annotations

from datetime import datetime, timedelta, timezone

from baseliner_server.db.models import Device, Run, RunStatus


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
        auth_token_hash="testhash",  # required (nullable=False)
    )
    db.add(d)
    db.flush()
    return d


def _create_run(
    db,
    *,
    device_id,
    started_at: datetime,
    ended_at: datetime | None,
    status: RunStatus,
) -> Run:
    r = Run(
        device_id=device_id,
        started_at=started_at,
        ended_at=ended_at,
        effective_policy_hash="deadbeef",
        status=status,
        agent_version="0.1.0-dev",
        policy_snapshot={"policy_id": "p1"},
        summary={"ok": 1, "failed": 0},
    )
    db.add(r)
    db.flush()
    return r


def test_runs_total_and_pagination(client, db):
    """
    Verifies:
      - total is full count (pre-pagination)
      - limit/offset works
      - items are ordered by started_at DESC
      - status is serialized as a string (enum value)
    """
    d1 = _create_device(db, device_key="D1")

    base = utcnow() - timedelta(minutes=60)
    # Create 12 runs, 1 minute apart, increasing started_at => newest is last created
    for i in range(12):
        st = base + timedelta(minutes=i)
        en = st + timedelta(seconds=10)
        status = RunStatus.succeeded if i % 2 == 0 else RunStatus.failed
        _create_run(db, device_id=d1.id, started_at=st, ended_at=en, status=status)

    db.commit()

    # Page 1
    r1 = client.get("/api/v1/admin/runs?limit=5&offset=0")
    assert r1.status_code == 200
    j1 = r1.json()

    assert j1["total"] == 12
    assert j1["limit"] == 5
    assert j1["offset"] == 0
    assert len(j1["items"]) == 5

    # Confirm ordering: started_at is descending
    started = [it["started_at"] for it in j1["items"]]
    assert started == sorted(started, reverse=True)

    # Status is serialized as string, not enum object
    for it in j1["items"]:
        assert isinstance(it["status"], (str, type(None)))
        if it["status"] is not None:
            assert it["status"] in {"succeeded", "failed", "running", "partial"}

    # Page 2 (offset)
    r2 = client.get("/api/v1/admin/runs?limit=5&offset=5")
    assert r2.status_code == 200
    j2 = r2.json()

    assert j2["total"] == 12
    assert j2["limit"] == 5
    assert j2["offset"] == 5
    assert len(j2["items"]) == 5

    # Page 3 (last page)
    r3 = client.get("/api/v1/admin/runs?limit=5&offset=10")
    assert r3.status_code == 200
    j3 = r3.json()

    assert j3["total"] == 12
    assert j3["limit"] == 5
    assert j3["offset"] == 10
    assert len(j3["items"]) == 2


def test_runs_device_id_filter(client, db):
    """
    Verifies device_id filter affects BOTH items and total.
    """
    d1 = _create_device(db, device_key="D1")
    d2 = _create_device(db, device_key="D2")

    now = utcnow()

    # d1 gets 3 runs, d2 gets 7 runs
    for i in range(3):
        st = now - timedelta(minutes=10 - i)
        _create_run(db, device_id=d1.id, started_at=st, ended_at=st + timedelta(seconds=5), status=RunStatus.succeeded)

    for i in range(7):
        st = now - timedelta(minutes=20 - i)
        _create_run(db, device_id=d2.id, started_at=st, ended_at=st + timedelta(seconds=5), status=RunStatus.failed)

    db.commit()

    # Filter d1
    r1 = client.get(f"/api/v1/admin/runs?device_id={d1.id}&limit=50&offset=0")
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["total"] == 3
    assert len(j1["items"]) == 3
    assert all(it["device_id"] == str(d1.id) for it in j1["items"])

    # Filter d2
    r2 = client.get(f"/api/v1/admin/runs?device_id={d2.id}&limit=50&offset=0")
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["total"] == 7
    assert len(j2["items"]) == 7
    assert all(it["device_id"] == str(d2.id) for it in j2["items"])


def test_runs_status_field_is_stable_string(client, db):
    """
    Quick focused test: RunStatus enum should serialize to its .value string.
    """
    d = _create_device(db, device_key="D3")
    st = utcnow() - timedelta(minutes=1)

    _create_run(db, device_id=d.id, started_at=st, ended_at=None, status=RunStatus.running)
    db.commit()

    r = client.get("/api/v1/admin/runs?limit=10&offset=0")
    assert r.status_code == 200
    j = r.json()

    assert j["total"] == 1
    assert len(j["items"]) == 1
    assert j["items"][0]["status"] == "running"
