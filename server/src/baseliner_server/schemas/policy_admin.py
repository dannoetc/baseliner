from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UpsertPolicyRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    schema_version: str = "1.0"
    document: dict[str, Any]
    is_active: bool = True


class UpsertPolicyResponse(BaseModel):
    policy_id: str
    name: str
    is_active: bool


class PolicySummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    schema_version: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PoliciesListResponse(BaseModel):
    items: list[PolicySummary]
    limit: int
    offset: int
    total: int


class PolicyDetailResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    schema_version: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    document: dict[str, Any]


# Backwards-compatible aliases
PolicyUpsertRequest = UpsertPolicyRequest
PolicyUpsertResponse = UpsertPolicyResponse
