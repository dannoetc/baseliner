from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """Base schema with SQLAlchemy ORM support (pydantic v2)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class RunRollup(ORMModel):
    id: str
    device_id: str

    correlation_id: str | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None
    agent_version: str | None = None
    effective_policy_hash: str | None = None

    # operator qol
    items_total: int | None = None
    items_failed: int | None = None
    items_changed: int | None = None
    duration_ms: int | None = None

    # raw summary for forward-compat (clients can read additional keys)
    summary: dict[str, Any] = Field(default_factory=dict)

    # convenience link (relative path) to fetch full run detail
    detail_path: str | None = None


class DeviceRunsResponse(ORMModel):
    device_id: str
    items: list[RunRollup]
    limit: int
    offset: int
    total: int = 0
