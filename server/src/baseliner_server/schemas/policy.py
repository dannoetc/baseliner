from pydantic import BaseModel
from typing import Any


class EffectivePolicyResponse(BaseModel):
    policy_id: str | None = None
    policy_name: str | None = None
    schema_version: str | None = None
    mode: str = "enforce"
    document: dict[str, Any] = {}

    # new
    effective_policy_hash: str | None = None
    sources: list[dict[str, Any]] = []
