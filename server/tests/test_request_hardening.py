from __future__ import annotations

from datetime import datetime, timezone

from baseliner_server.api.deps import hash_token
from baseliner_server.db.models import Device, Run
from baseliner_server.middleware.rate_limit import InMemoryRateLimiter, RateLimitConfig
from baseliner_server.middleware.request_size import RequestSizeLimits
from fastapi.testclient import TestClient
from sqlalchemy import select


def _create_device(db, token: str = "token") -> Device:
    device = Device(
        device_key="device-key",
        hostname="host",
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


def _minimal_report_payload() -> dict:
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "succeeded",
        "items": [],
        "summary": {},
    }


def test_request_size_limit_rejects_oversized_body(client: TestClient):
    # Force a tiny limit so we can exercise the middleware.
    original = client.app.state.request_size_limits
    client.app.state.request_size_limits = RequestSizeLimits(
        default_max_bytes=100, device_reports_max_bytes=100
    )
    try:
        # Not valid JSON, but that doesn't matter: the size check happens before parsing.
        resp = client.post(
            "/api/v1/device/reports",
            data=("x" * 200).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413, resp.text
        assert resp.json().get("detail") == "Request body too large"
    finally:
        client.app.state.request_size_limits = original


def test_device_reports_rate_limited_by_device_id(client: TestClient, db):
    token = "rate-limit-device"
    _create_device(db, token)

    original_cfg = client.app.state.rate_limit_config
    original_limiter = client.app.state.rate_limiter
    client.app.state.rate_limit_config = RateLimitConfig(
        enabled=True,
        reports_per_minute=1,
        reports_burst=1,
        reports_ip_per_minute=1,
        reports_ip_burst=1,
    )
    client.app.state.rate_limiter = InMemoryRateLimiter()

    try:
        payload = _minimal_report_payload()

        r1 = client.post(
            "/api/v1/device/reports",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert r1.status_code == 200, r1.text

        r2 = client.post(
            "/api/v1/device/reports",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert r2.status_code == 429, r2.text
        assert "Retry-After" in r2.headers

        # Only one run should exist (second request blocked).
        runs = db.scalars(select(Run)).all()
        assert len(runs) == 1
    finally:
        client.app.state.rate_limit_config = original_cfg
        client.app.state.rate_limiter = original_limiter


def test_device_reports_rate_limited_by_ip_when_unauth(client: TestClient):
    original_cfg = client.app.state.rate_limit_config
    original_limiter = client.app.state.rate_limiter
    client.app.state.rate_limit_config = RateLimitConfig(
        enabled=True,
        reports_per_minute=1,
        reports_burst=1,
        reports_ip_per_minute=1,
        reports_ip_burst=1,
    )
    client.app.state.rate_limiter = InMemoryRateLimiter()

    try:
        payload = _minimal_report_payload()

        # First request: not authenticated (401), but still consumes the IP bucket.
        r1 = client.post("/api/v1/device/reports", json=payload)
        assert r1.status_code in (401, 403)

        # Second request: blocked by IP limiter.
        r2 = client.post("/api/v1/device/reports", json=payload)
        assert r2.status_code == 429, r2.text
        assert "Retry-After" in r2.headers
    finally:
        client.app.state.rate_limit_config = original_cfg
        client.app.state.rate_limiter = original_limiter
