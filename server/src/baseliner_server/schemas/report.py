from pydantic import BaseModel, Field
from typing import Any
from datetime import datetime


class ReportRunItem(BaseModel):
    resource_type: str
    resource_id: str
    name: str | None = None
    ordinal: int = 0

    compliant_before: bool | None = None
    compliant_after: bool | None = None
    changed: bool = False
    reboot_required: bool = False

    status_detect: str = "not_run"
    status_remediate: str = "not_run"
    status_validate: str = "not_run"

    started_at: datetime | None = None
    ended_at: datetime | None = None

    evidence: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)


class ReportLogEvent(BaseModel):
    ts: datetime | None = None
    level: str = "info"
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    run_item_ordinal: int | None = None


class SubmitReportRequest(BaseModel):
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "running"
    agent_version: str | None = None
    
    effective_policy_hash: str | None = None

    policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)

    items: list[ReportRunItem] = Field(default_factory=list)
    logs: list[ReportLogEvent] = Field(default_factory=list)


class SubmitReportResponse(BaseModel):
    run_id: str
