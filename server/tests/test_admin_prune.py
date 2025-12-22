from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from baseliner_server.db.models import (
    Device,
    LogEvent,
    LogLevel,
    Run,
    RunItem,
    RunStatus,
    StepStatus,
)


def _utc_naive(dt: datetime) -> datetime:
    # The app uses naive datetimes in a few admin endpoints for sqlite test friendliness.
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_admin_prune_runs_dry_run_and_delete(client, db):
    # Arrange: one device with three runs; two are older than 30 days.
    dev = Device(
        id=uuid.uuid4(),
        device_key="TEST-PRUNE-001",
        hostname="t",
        os="windows",
        os_version="1",
        arch="x64",
        agent_version="0.1.0-dev",
        tags={},
        enrolled_at=_utc_naive(datetime.now(timezone.utc)),
        last_seen_at=_utc_naive(datetime.now(timezone.utc)),
        auth_token_hash="x",
    )
    db.add(dev)
    db.commit()

    now = datetime.now(timezone.utc)
    r_recent = Run(
        id=uuid.uuid4(),
        device_id=dev.id,
        started_at=_utc_naive(now - timedelta(minutes=5)),
        ended_at=_utc_naive(now - timedelta(minutes=4)),
        status=RunStatus.succeeded,
        agent_version="0.1.0-dev",
        effective_policy_hash="h",
        policy_snapshot={},
        summary={"items_total": 1},
    )

    r_old1 = Run(
        id=uuid.uuid4(),
        device_id=dev.id,
        started_at=_utc_naive(now - timedelta(days=40)),
        ended_at=_utc_naive(now - timedelta(days=40, minutes=-1)),
        status=RunStatus.succeeded,
        agent_version="0.1.0-dev",
        effective_policy_hash="h",
        policy_snapshot={},
        summary={"items_total": 1},
    )

    r_old2 = Run(
        id=uuid.uuid4(),
        device_id=dev.id,
        started_at=_utc_naive(now - timedelta(days=35)),
        ended_at=_utc_naive(now - timedelta(days=35, minutes=-1)),
        status=RunStatus.failed,
        agent_version="0.1.0-dev",
        effective_policy_hash="h",
        policy_snapshot={},
        summary={"items_total": 1},
    )

    db.add_all([r_recent, r_old1, r_old2])
    db.flush()

    for r in [r_recent, r_old1, r_old2]:
        item = RunItem(
            id=uuid.uuid4(),
            run_id=r.id,
            resource_type="script.powershell",
            resource_id="x",
            name="x",
            ordinal=0,
            compliant_before=True,
            compliant_after=True,
            changed=False,
            reboot_required=False,
            status_detect=StepStatus.ok,
            status_remediate=StepStatus.skipped,
            status_validate=StepStatus.ok,
            started_at=r.started_at,
            ended_at=r.ended_at,
            evidence={},
            error={},
        )
        db.add(item)
        db.flush()

        log = LogEvent(
            id=uuid.uuid4(),
            run_id=r.id,
            run_item_id=item.id,
            ts=r.ended_at,
            level=LogLevel.info,
            message="m",
            data={},
        )
        db.add(log)

    db.commit()

    # Dry-run
    resp = client.post(
        "/api/v1/admin/maintenance/prune",
        json={"keep_days": 30, "keep_runs_per_device": 100, "dry_run": True, "batch_size": 50},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["dry_run"] is True
    assert body["runs_targeted"] == 2
    assert body["counts"]["runs"] == 2
    assert body["counts"]["run_items"] == 2
    assert body["counts"]["log_events"] == 2

    # Execute delete
    resp2 = client.post(
        "/api/v1/admin/maintenance/prune",
        json={"keep_days": 30, "keep_runs_per_device": 100, "dry_run": False, "batch_size": 50},
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["dry_run"] is False
    assert body2["counts"]["runs"] == 2

    remaining = list(db.scalars(select(Run).where(Run.device_id == dev.id)).all())
    assert len(remaining) == 1
    assert str(remaining[0].id) == str(r_recent.id)
