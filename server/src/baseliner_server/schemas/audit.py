from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEvent(BaseModel):
    id: str
    ts: datetime

    actor_type: str
    actor_id: str

    action: str
    target_type: str | None = None
    target_id: str | None = None

    request_method: str | None = None
    request_path: str | None = None
    correlation_id: str | None = None
    remote_addr: str | None = None

    data: dict[str, Any] = {}


class AuditListResponse(BaseModel):
    items: list[AuditEvent]
    limit: int
    next_cursor: str | None = None
