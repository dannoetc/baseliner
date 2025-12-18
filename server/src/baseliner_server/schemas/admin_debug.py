from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from baseliner_server.schemas.admin_list import DeviceSummary
from baseliner_server.schemas.policy import EffectivePolicyResponse
from baseliner_server.schemas.run_detail import RunItemDetail


class PolicyAssignmentDebugOut(BaseModel):
    assignment_id: str
    created_at: datetime | None = None

    policy_id: str
    policy_name: str
    priority: int
    mode: str
    is_active: bool


class RunDebugSummary(BaseModel):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None
    agent_version: str | None = None
    effective_policy_hash: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)

    # Convenience link (relative path) to fetch full run detail
    detail_path: str | None = None

    # Operator QoL (so you don't have to open run detail for common questions)
    items_total: int | None = None
    items_failed: int | None = None
    items_changed: int | None = None
    duration_ms: int | None = None


class DeviceDebugResponse(BaseModel):
    device: DeviceSummary
    assignments: list[PolicyAssignmentDebugOut] = Field(default_factory=list)

    effective_policy: EffectivePolicyResponse

    last_run: RunDebugSummary | None = None
    last_run_items: list[RunItemDetail] = Field(default_factory=list)
