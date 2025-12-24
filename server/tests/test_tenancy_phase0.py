from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from baseliner_server.core.tenancy import DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME, ensure_default_tenant
from baseliner_server.db.models import Device, EnrollToken, Run, Tenant


def test_phase0_default_tenant_and_row_stamping(client, db):
    # Ensure default tenant exists (create_all() test DB path)
    ensure_default_tenant(db)

    tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    assert tenant is not None
    assert tenant.name == DEFAULT_TENANT_NAME

    # Create an enroll token via admin API
    resp = client.post(
        "/api/v1/admin/enroll-tokens",
        json={"ttl_seconds": 3600, "single_use": True, "metadata": {"purpose": "tenancy-test"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    raw_token = body["token"]
    token_id = uuid.UUID(body["token_id"])

    tok_row = db.scalar(select(EnrollToken).where(EnrollToken.id == token_id))
    assert tok_row is not None
    assert tok_row.tenant_id == DEFAULT_TENANT_ID

    # Enroll a device using that token
    enroll_resp = client.post(
        "/api/v1/enroll",
        json={
            "enroll_token": raw_token,
            "device_key": "TENANT-DEV-01",
            "hostname": "tenant-host",
            "os": "linux",
            "os_version": "1.0",
            "arch": "x64",
            "agent_version": "0.2.2-test",
            "tags": {"env": "test"},
        },
    )
    assert enroll_resp.status_code == 200, enroll_resp.text
    enroll_body = enroll_resp.json()
    device_id = uuid.UUID(enroll_body["device_id"])
    device_token = enroll_body["device_token"]

    dev = db.get(Device, device_id)
    assert dev is not None
    assert dev.tenant_id == DEFAULT_TENANT_ID

    # Post a report; ensure the created run is tenant-stamped.
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
    }

    report_resp = client.post(
        "/api/v1/device/reports",
        headers={"Authorization": f"Bearer {device_token}"},
        json=report,
    )
    assert report_resp.status_code == 200, report_resp.text

    run = db.scalar(select(Run).where(Run.device_id == dev.id))
    assert run is not None
    assert run.tenant_id == DEFAULT_TENANT_ID
