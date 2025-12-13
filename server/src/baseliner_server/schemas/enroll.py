from pydantic import BaseModel, Field
from typing import Any


class EnrollRequest(BaseModel):
    enroll_token: str = Field(..., min_length=10)

    device_key: str = Field(..., min_length=8, max_length=128)
    hostname: str | None = None
    os: str | None = "windows"
    os_version: str | None = None
    arch: str | None = None
    agent_version: str | None = None
    tags: dict[str, Any] = Field(default_factory=dict)


class EnrollResponse(BaseModel):
    device_id: str
    device_token: str
