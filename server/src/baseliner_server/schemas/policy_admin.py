from pydantic import BaseModel, Field
from typing import Any


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


# Backwards-compatible aliases (older clients/tests referenced these names)
PolicyUpsertRequest = UpsertPolicyRequest
PolicyUpsertResponse = UpsertPolicyResponse
