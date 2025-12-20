from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """Base schema with SQLAlchemy ORM support (pydantic v2)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class RunSummaryLite(ORMModel):
    id: str
    correlation_id: str | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None
    agent_version: str | None = None
    effective_policy_hash: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class DeviceHealth(ORMModel):
    status: str  # "ok" | "warn" | "offline"
    now: datetime
    last_seen_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None

    seen_age_seconds: int | None = None
    run_age_seconds: int | None = None

    stale: bool = False
    offline: bool = False
    reason: str | None = None


class DeviceSummary(ORMModel):
    id: str
    device_key: str
    hostname: str | None = None
    os: str | None = None
    os_version: str | None = None
    arch: str | None = None

    agent_version: str | None = None
    enrolled_at: datetime | None = None

    tags: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime | None = None

    last_run: RunSummaryLite | None = None
    health: DeviceHealth | None = None


# Backwards-compatible alias used by some earlier branches/tooling.
# (Kept here so ``from baseliner_server.schemas.admin_list import DeviceAdminOut``
# continues to work.)
DeviceAdminOut = DeviceSummary


class DevicesListResponse(ORMModel):
    items: list[DeviceSummary]
    limit: int
    offset: int


class RunSummary(ORMModel):
    id: str
    device_id: str | None = None

    correlation_id: str | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None
    agent_version: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)


class RunsListResponse(ORMModel):
    items: list[RunSummary]
    limit: int
    offset: int
    total: int = 0
