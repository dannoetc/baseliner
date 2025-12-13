from pydantic import BaseModel
from datetime import datetime
from typing import Any


class DeviceSummary(BaseModel):
    id: str
    device_key: str
    hostname: str | None = None
    os: str | None = None
    os_version: str | None = None
    arch: str | None = None
    agent_version: str | None = None
    enrolled_at: datetime
    last_seen_at: datetime | None = None
    tags: dict[str, Any] = {}


class DevicesListResponse(BaseModel):
    items: list[DeviceSummary]
    limit: int
    offset: int


class RunSummary(BaseModel):
    id: str
    device_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    agent_version: str | None = None
    summary: dict[str, Any] = {}
    policy_snapshot: dict[str, Any] = {}


class RunsListResponse(BaseModel):
    items: list[RunSummary]
    limit: int
    offset: int
