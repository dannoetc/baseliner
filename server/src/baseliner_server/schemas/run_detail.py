from pydantic import BaseModel
from datetime import datetime
from typing import Any


class RunItemDetail(BaseModel):
    id: str
    ordinal: int
    resource_type: str
    resource_id: str
    name: str | None = None

    compliant_before: bool | None = None
    compliant_after: bool | None = None
    changed: bool
    reboot_required: bool

    status_detect: str
    status_remediate: str
    status_validate: str

    started_at: datetime | None = None
    ended_at: datetime | None = None

    evidence: dict[str, Any] = {}
    error: dict[str, Any] = {}


class LogEventDetail(BaseModel):
    id: str
    ts: datetime
    level: str
    message: str
    data: dict[str, Any] = {}
    run_item_id: str | None = None


class RunDetailResponse(BaseModel):
    id: str
    device_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    agent_version: str | None = None
    summary: dict[str, Any] = {}
    policy_snapshot: dict[str, Any] = {}

    items: list[RunItemDetail] = []
    logs: list[LogEventDetail] = []
