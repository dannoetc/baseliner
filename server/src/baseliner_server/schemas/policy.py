from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EffectivePolicyResponse(BaseModel):
    policy_id: str | None = None
    policy_name: str | None = None
    schema_version: str | None = None
    mode: str = "enforce"
    document: dict[str, Any] = Field(default_factory=dict)

    # new
    effective_policy_hash: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)

    # operator/debug compile metadata (why each resource was selected)
    # NOTE: not used by the agent; not included in effective_policy_hash.
    compile: dict[str, Any] = Field(default_factory=dict)
