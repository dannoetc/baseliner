from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device, Run, RunStatus


def _create_device(db, token: str = "token") -> Device:
    device = Device(
        device_key="device-key",
        hostname="host",  # optional but useful for debugging
        os="linux",
        os_version="1.0",
        arch="x64",
        agent_version="1.2.3",
        auth_token_hash=hash_token(token),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def _post_report(client: TestClient, token: str, payload: dict) -> dict:
    resp = client.post(
        "/api/v1/device/reports",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_zero_items_preserves_failed_status(client, db):
    token = "fail-token"
    _create_device(db, token)

    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "items": [],
        "summary": {},
    }

    _post_report(client, token, payload)

    run = db.scalar(select(Run))
    assert run is not None
    assert run.status == RunStatus.failed
    assert run.summary["items_total"] == 0
    assert run.summary["items_failed"] == 0


def test_zero_items_succeeded_status(client, db):
    token = "ok-token"
    _create_device(db, token)

    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
    }

    _post_report(client, token, payload)

    run = db.scalar(select(Run))
    assert run is not None
    assert run.status == RunStatus.succeeded
    assert run.summary["items_total"] == 0
    assert run.summary["items_failed"] == 0


def test_report_idempotency_key_deduplicates_runs(client, db):
    token = "idem-token"
    _create_device(db, token)

    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
        "idempotency_key": "report-123",
    }

    first = _post_report(client, token, payload)
    second = _post_report(client, token, payload)

    assert first["run_id"] == second["run_id"]

    runs = db.scalars(select(Run)).all()
    assert len(runs) == 1
    assert runs[0].idempotency_key == "report-123"


def test_report_idempotency_key_preserves_original_run(client, db):
    token = "idem-preserve"
    _create_device(db, token)

    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {"custom": "first"},
        "idempotency_key": "report-456",
    }

    first = _post_report(client, token, payload)

    second_payload = {
        **payload,
        "summary": {"custom": "second"},
        "status": "failed",
    }

    second = _post_report(client, token, second_payload)

    assert first["run_id"] == second["run_id"]

    run = db.scalar(select(Run))
    assert run is not None
    assert run.summary.get("custom") == "first"
    assert run.status == RunStatus.succeeded
