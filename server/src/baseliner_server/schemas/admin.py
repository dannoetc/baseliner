"""Admin-facing request/response schemas.

The server has a few schema modules (policy upserts, device/run list responses,
run details, etc.). Historically, route handlers and test harnesses imported
those models from ``baseliner_server.schemas.admin``.

To keep imports stable while we decide where each schema *should* live, this
module:
  - defines the core admin request/response models
  - re-exports list/run/policy models from their specialized modules

This lets callers do:

    from baseliner_server.schemas.admin import DevicesListResponse, RunOutFull

without having to know the internal module layout.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Core admin request/response models (defined here)
# ---------------------------------------------------------------------------


class CreateEnrollTokenRequest(BaseModel):
    expires_at: datetime | None = None
    note: str | None = None


class CreateEnrollTokenResponse(BaseModel):
    enroll_token: str
    expires_at: datetime | None = None


class AssignPolicyRequest(BaseModel):
    device_id: str
    policy_name: str
    mode: str = "enforce"
    priority: int = 100


class AssignPolicyResponse(BaseModel):
    # Current API uses a simple ok flag; richer responses can be added later.
    ok: bool


class PolicyAssignmentOut(BaseModel):
    policy_id: str
    policy_name: str
    priority: int
    mode: str
    is_active: bool


class DeviceAssignmentsResponse(BaseModel):
    device_id: str
    assignments: list[PolicyAssignmentOut]


class ClearAssignmentsResponse(BaseModel):
    device_id: str
    removed: int


# ---------------------------------------------------------------------------
# Policy upsert models (re-exported for backwards compatibility)
# ---------------------------------------------------------------------------

# Canonical definitions live in schemas/policy_admin.py.
from .policy_admin import (  # noqa: E402
    PolicyUpsertRequest,
    PolicyUpsertResponse,
    UpsertPolicyRequest,
    UpsertPolicyResponse,
)


# ---------------------------------------------------------------------------
# Device/run list response models (re-exported)
# ---------------------------------------------------------------------------

# Canonical definitions live in schemas/admin_list.py.
from .admin_list import (  # noqa: E402
    DeviceAdminOut,
    DevicesListResponse,
    RunSummary,
    RunsListResponse,
)


# ---------------------------------------------------------------------------
# Run detail models (re-exported)
# ---------------------------------------------------------------------------

# Canonical definitions live in schemas/run_detail.py.
from .run_detail import (  # noqa: E402
    LogEventDetail,
    RunDetailResponse,
    RunItemDetail,
    RunOutFull,
)


# ---------------------------------------------------------------------------
# Device debug bundle (re-exported)
# ---------------------------------------------------------------------------

from .admin_debug import (  # noqa: E402
    DeviceDebugResponse,
    PolicyAssignmentDebugOut,
    RunDebugSummary,
)


__all__ = [
    # enroll
    "CreateEnrollTokenRequest",
    "CreateEnrollTokenResponse",
    # assignments
    "AssignPolicyRequest",
    "AssignPolicyResponse",
    "PolicyAssignmentOut",
    "DeviceAssignmentsResponse",
    "ClearAssignmentsResponse",
    # policy upsert
    "UpsertPolicyRequest",
    "UpsertPolicyResponse",
    "PolicyUpsertRequest",
    "PolicyUpsertResponse",
    # lists
    "DeviceAdminOut",
    "DevicesListResponse",
    "RunSummary",
    "RunsListResponse",
    # run details
    "RunItemDetail",
    "LogEventDetail",
    "RunDetailResponse",
    "RunOutFull",
    # debug bundle
    "DeviceDebugResponse",
    "PolicyAssignmentDebugOut",
    "RunDebugSummary",
]
