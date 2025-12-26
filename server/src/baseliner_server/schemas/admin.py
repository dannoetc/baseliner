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
    # If provided, the token becomes invalid after this time.
    expires_at: datetime | None = None

    # Convenience: if expires_at is omitted, server can compute expires_at = now + ttl_seconds.
    ttl_seconds: int | None = None

    note: str | None = None


class CreateEnrollTokenResponse(BaseModel):
    token_id: str
    token: str
    enroll_token: str
    expires_at: datetime | None = None


class EnrollTokenSummary(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime | None = None
    used_at: datetime | None = None
    used_by_device_id: str | None = None
    note: str | None = None
    is_used: bool
    is_expired: bool


class EnrollTokensListResponse(BaseModel):
    items: list[EnrollTokenSummary]
    total: int
    limit: int
    offset: int


class RevokeEnrollTokenRequest(BaseModel):
    reason: str | None = None


class RevokeEnrollTokenResponse(BaseModel):
    token_id: str
    revoked_at: datetime
    expires_at: datetime | None = None
    note: str | None = None


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


class RemoveAssignmentResponse(BaseModel):
    device_id: str
    policy_id: str
    removed: int


class DeleteDeviceResponse(BaseModel):
    device_id: str
    status: str
    deleted_at: datetime | None = None
    deleted_reason: str | None = None
    token_revoked_at: datetime | None = None
    assignments_removed: int = 0


class RestoreDeviceResponse(BaseModel):
    device_id: str
    status: str
    restored_at: datetime
    device_token: str


class DeviceLifecycleRequest(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] | None = None


# Backwards-compatible alias used by older admin endpoints.
DeleteDeviceRequest = DeviceLifecycleRequest


class DeactivateDeviceResponse(BaseModel):
    device_id: str
    tenant_id: str
    status: str
    deactivated_at: datetime
    token_revoked_at: datetime | None = None
    revoked_tokens: bool = False


class ReactivateDeviceResponse(BaseModel):
    device_id: str
    tenant_id: str
    status: str
    reactivated_at: datetime



class DeviceAuthTokenSummary(BaseModel):
    id: str
    token_hash_prefix: str | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    replaced_by_id: str | None = None
    is_active: bool


class DeviceTokensListResponse(BaseModel):
    device_id: str
    items: list[DeviceAuthTokenSummary] = Field(default_factory=list)


class RevokeDeviceTokenResponse(BaseModel):
    device_id: str
    status: str
    token_revoked_at: datetime
    device_token: str


class RotateDeviceTokenResponse(BaseModel):
    device_id: str
    tenant_id: str
    token: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Policy upsert models (re-exported for backwards compatibility)
# ---------------------------------------------------------------------------

# Canonical definitions live in schemas/policy_admin.py.
# ---------------------------------------------------------------------------
# Device debug bundle (re-exported)
# ---------------------------------------------------------------------------
from .admin_debug import (  # noqa: E402
    DeviceDebugResponse,
    PolicyAssignmentDebugOut,
    RunDebugSummary,
)

# ---------------------------------------------------------------------------
# Device/run list response models (re-exported)
# ---------------------------------------------------------------------------
# Canonical definitions live in schemas/admin_list.py.
from .admin_list import (  # noqa: E402
    DeviceAdminOut,
    DevicesListResponse,
    RunsListResponse,
    RunSummary,
)
from .policy_admin import (  # noqa: E402
    PolicyUpsertRequest,
    PolicyUpsertResponse,
    UpsertPolicyRequest,
    UpsertPolicyResponse,
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
    "RemoveAssignmentResponse",
    "DeleteDeviceResponse",
    "RestoreDeviceResponse",
    "DeviceLifecycleRequest",
    "DeactivateDeviceResponse",
    "ReactivateDeviceResponse",
    "DeviceAuthTokenSummary",
    "DeviceTokensListResponse",
    "RevokeDeviceTokenResponse",
    "RotateDeviceTokenResponse",
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
    "DeleteDeviceRequest",
    "PolicyAssignmentDebugOut",
    "RunDebugSummary",
]
