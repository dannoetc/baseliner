from pydantic import BaseModel
from datetime import datetime


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
    ok: bool
