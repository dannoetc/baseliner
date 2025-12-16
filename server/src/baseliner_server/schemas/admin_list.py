from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunSummaryLite(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: Optional[str] = None
    agent_version: Optional[str] = None
    effective_policy_hash: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)


class DeviceHealth(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    now: datetime

    last_seen_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None

    seen_age_seconds: Optional[int] = None
    run_age_seconds: Optional[int] = None

    stale: bool = False
    offline: bool = False
    reason: Optional[str] = None


class DeviceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_key: str

    hostname: Optional[str] = None
    os: Optional[str] = None
    os_version: Optional[str] = None
    arch: Optional[str] = None
    agent_version: Optional[str] = None

    enrolled_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    tags: dict[str, Any] = Field(default_factory=dict)

    # If these fields aren't declared, FastAPI will DROP them from the response_model.
    last_run: Optional[RunSummaryLite] = None
    health: Optional[DeviceHealth] = None


class DevicesListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[DeviceSummary]
    limit: int
    offset: int


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: Optional[str] = None
    agent_version: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)


class RunsListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[RunSummary]
    limit: int
    offset: int
    total: int
