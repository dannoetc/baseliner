from __future__ import annotations

from datetime import datetime, timedelta, timezone

from baseliner_server.db.models import Device, Run, RunStatus
import httpx 

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _admin_devices_path(client) -> str:
    """
    Discover the mounted path for the admin devices endpoint.

    This prevents tests from hardcoding /api/v1 when the router
    may be mounted at / (or mounted with a different prefix).
    """
    for r in getattr(client.app, "routes", []):
        path = getattr(r, "path", None)
        if isinstance(path, str) and path.endswith("/admin/devices"):
            return path
    raise AssertionError("admin/devices route not registered on the app")


import httpx

def _get_devices(client, qs: str) -> httpx.Response:
    path = _admin_devices_path(client)
    return client.get(f"{path}{qs}")



def _create_device(db, *, device_key: str, last_seen_at: datetime | None) -> Device:
    d = Device(
        device_key=device_key,
        hostname="host-" + device_key,
        os="windows",
        os_version="10.0",
        arch="x64",
        agent_version="0.1.0-dev",
        tags={"env": "test"},
        enrolled_at=utcnow(),
        last_seen_at=last_seen_at,
        auth_token_hash="testhash",  # REQUIRED (nullable=False)
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


def _get_device(resp_json: dict, device_key: str) -> dict:
    return next(x for x in resp_json["items"] if x["device_key"] == device_key)


def test_health_ok(client, db):
    """
    last_seen recent, latest run succeeded and not stale => ok
    """
    dev = _create_device(db, device_key="OK1", last_seen_at=utcnow() - timedelta(seconds=10))
    end = utcnow() - timedelta(seconds=30)
    _create_run(
        db,
        device_id=dev.id,
        started_at=end - timedelta(seconds=20),
        ended_at=end,
        status=RunStatus.succeeded,
    )
    db.commit()

    r = _get_devices(
        client,
        "?include_health=true&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "OK1")

    assert d["health"]["status"] == "ok"
    assert d["health"]["offline"] is False
    assert d["health"]["stale"] is False
    assert d["last_run"] is not None
    assert (d["last_run"]["status"] or "").lower() == "succeeded"


def test_health_warn_stale_no_runs(client, db):
    """
    last_seen recent, but no runs exist => stale True => warn
    """
    _create_device(db, device_key="STL0", last_seen_at=utcnow() - timedelta(seconds=10))
    db.commit()

    r = _get_devices(
        client,
        "?include_health=true&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "STL0")

    assert d.get("last_run") is None
    assert d["health"]["status"] == "warn"
    assert d["health"]["offline"] is False
    assert d["health"]["stale"] is True
    assert "stale" in (d["health"].get("reason") or "").lower()


def test_health_warn_stale_old_run(client, db):
    """
    last_seen recent, but latest run is older than stale_after_seconds => warn stale
    """
    dev = _create_device(db, device_key="STL1", last_seen_at=utcnow() - timedelta(seconds=10))
    old_end = utcnow() - timedelta(seconds=4000)
    _create_run(
        db,
        device_id=dev.id,
        started_at=old_end - timedelta(seconds=30),
        ended_at=old_end,
        status=RunStatus.succeeded,
    )
    db.commit()

    r = _get_devices(
        client,
        "?include_health=true&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "STL1")

    assert d["health"]["status"] == "warn"
    assert d["health"]["offline"] is False
    assert d["health"]["stale"] is True


def test_health_offline(client, db):
    """
    last_seen too old => offline
    """
    dev = _create_device(db, device_key="OFF1", last_seen_at=utcnow() - timedelta(seconds=999999))
    end = utcnow() - timedelta(seconds=30)
    _create_run(
        db,
        device_id=dev.id,
        started_at=end - timedelta(seconds=20),
        ended_at=end,
        status=RunStatus.succeeded,
    )
    db.commit()

    r = _get_devices(
        client,
        "?include_health=true&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "OFF1")

    assert d["health"]["status"] == "offline"
    assert d["health"]["offline"] is True
    assert "checked in" in (d["health"].get("reason") or "").lower()


def test_health_warn_failed_run(client, db):
    """
    last_seen recent, latest run failed => warn "latest run failed"
    """
    dev = _create_device(db, device_key="FLD1", last_seen_at=utcnow() - timedelta(seconds=10))
    end = utcnow() - timedelta(seconds=30)
    _create_run(
        db,
        device_id=dev.id,
        started_at=end - timedelta(seconds=20),
        ended_at=end,
        status=RunStatus.failed,
    )
    db.commit()

    r = _get_devices(
        client,
        "?include_health=true&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "FLD1")

    assert d["health"]["status"] == "warn"
    assert d["health"]["offline"] is False
    assert (d["health"].get("reason") or "").lower().startswith("latest run failed")


def test_last_run_and_health_present_without_flag(client, db):
    """
    last_run + basic health data should be returned even when include_health=false.
    """

    dev = _create_device(db, device_key="LITE1", last_seen_at=utcnow() - timedelta(seconds=120))
    end = utcnow() - timedelta(seconds=60)
    run = _create_run(
        db,
        device_id=dev.id,
        started_at=end - timedelta(seconds=20),
        ended_at=end,
        status=RunStatus.succeeded,
    )
    db.commit()

    r = _get_devices(
        client,
        "?include_health=false&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "LITE1")

    assert d["last_run"]["id"] == str(run.id)
    assert d["health"]["status"] == "ok"
    assert d["health"]["offline"] is False


def test_health_without_runs_even_when_flag_disabled(client, db):
    """
    Devices without runs still report health metadata with the default flag.
    """

    _create_device(db, device_key="NORN", last_seen_at=utcnow() - timedelta(seconds=10))
    db.commit()

    r = _get_devices(
        client,
        "?include_health=false&stale_after_seconds=1800&offline_after_seconds=3600",
    )
    assert r.status_code == 200
    d = _get_device(r.json(), "NORN")

    assert d.get("last_run") is None
    assert d["health"]["status"] == "warn"
    assert d["health"]["stale"] is True
