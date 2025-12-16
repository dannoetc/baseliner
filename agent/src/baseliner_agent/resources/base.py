from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceMeta:
    resource_type: str
    resource_id: str
    name: str | None
    ordinal: int


def meta_from_resource(res: dict[str, Any], *, ordinal: int) -> ResourceMeta:
    return ResourceMeta(
        resource_type=str((res.get("type") or "").strip()),
        resource_id=str((res.get("id") or "").strip()),
        name=res.get("name"),
        ordinal=int(ordinal),
    )
