"""Admin schemas for tenant lifecycle + admin key management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TenantSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    is_active: bool


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    is_active: bool = True


class CreateTenantResponse(BaseModel):
    tenant: TenantSummary


class TenantsListResponse(BaseModel):
    items: list[TenantSummary]

class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class UpdateTenantResponse(BaseModel):
    tenant: TenantSummary



class AdminKeySummary(BaseModel):
    id: str
    tenant_id: str
    scope: str
    created_at: datetime
    note: str | None = None


class IssueAdminKeyRequest(BaseModel):
    scope: str = Field("tenant_admin", description="superadmin or tenant_admin")
    note: str | None = None


class IssueAdminKeyResponse(BaseModel):
    key_id: str
    tenant_id: str
    scope: str
    created_at: datetime
    note: str | None = None

    # Returned only once.
    admin_key: str


class AdminKeysListResponse(BaseModel):
    items: list[AdminKeySummary]

class WhoAmIKey(BaseModel):
    id: str
    tenant_id: str
    scope: str
    created_at: datetime
    note: str | None = None


class WhoAmIResponse(BaseModel):
    tenant_id: str
    admin_key: WhoAmIKey
