from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.core.policy_hash import compute_effective_policy_hash
from baseliner_server.db.models import Device, Policy, PolicyAssignment


@dataclass(frozen=True)
class PolicySnapshot:
    mode: str
    policy: dict[str, Any]
    meta: dict[str, Any]


def _as_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        return uuid.UUID(value)
    raise TypeError(f"Expected UUID or str UUID, got {type(value)!r}")


def _resource_key(res: dict[str, Any]) -> tuple[str, str] | None:
    """
    Canonical de-dupe key for a resource.

    Default: (type, id)

    Special-case winget.package:
      - de-dupe by winget catalog identifier when present (package_id / packageId / wingetId),
        because different policies may use different stable ids for the same package.
    """
    rtype = (res.get("type") or "").strip().lower()
    if not rtype:
        return None

    # winget.package: prefer catalog id for identity
    if rtype == "winget.package":
        for k in ("package_id", "packageId", "winget_id", "wingetId", "package"):
            v = res.get(k)
            if isinstance(v, str) and v.strip():
                return (rtype, v.strip().lower())

    rid = (res.get("id") or "").strip()
    if not rid:
        return None
    return (rtype, rid.lower())



def _iter_resources(doc: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    if not doc:
        return []
    resources = doc.get("resources") or []
    if not isinstance(resources, list):
        return []
    # only pass through dict-like resources
    return [r for r in resources if isinstance(r, dict)]


def compile_effective_policy(db: Session, device: Device | str | uuid.UUID) -> PolicySnapshot:
    """
    Compile effective policy for a device based on active assignments.

    Priority semantics:
      - Lower numeric priority wins (0 beats 100 beats 9999).
      - We apply policies in ascending priority order and "first writer wins" per (type,id).

    Mode semantics:
      - "audit" only if *all* included assignments are audit
      - otherwise "enforce"
    """
    # Accept either a Device object or a device id
    if isinstance(device, Device):
        device_id = _as_uuid(str(device.id))
        device_key = device.device_key
    else:
        device_id = _as_uuid(device)
        dev = db.get(Device, device_id)
        device_key = dev.device_key if dev else None

    stmt = (
        select(PolicyAssignment, Policy)
        .join(Policy, Policy.id == PolicyAssignment.policy_id)
        .where(PolicyAssignment.device_id == device_id, Policy.is_active.is_(True))
        .order_by(PolicyAssignment.priority.asc())
    )

    rows = db.execute(stmt).all()

    # No assignments => empty effective policy
    if not rows:
        policy_doc: dict[str, Any] = {"resources": []}
        sources: list[dict[str, Any]] = []
        mode = "enforce"
        effective_hash = compute_effective_policy_hash(
            policy_id=None,
            policy_name=None,
            schema_version=None,
            mode=mode,
            document=policy_doc,
            sources=sources,
        )
        return PolicySnapshot(
            mode=mode,
            policy=policy_doc,
            meta={
                "device_id": str(device_id),
                "device_key": device_key,
                "assignments": 0,
                "sources": sources,
                "effective_hash": effective_hash,
            },
        )

    # Compute effective mode
    modes = [a.mode for (a, _p) in rows if a and a.mode]
    mode = "audit" if modes and all(m == "audit" for m in modes) else "enforce"

    # Merge resources
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    sources: list[dict[str, Any]] = []
    for (a, p) in rows:
        sources.append(
            {
                "policy_id": str(p.id),
                "policy_name": p.name,
                "priority": int(a.priority),
                "assignment_mode": a.mode,
                "schema_version": p.schema_version,
            }
        )

        for res in _iter_resources(p.document):
            key = _resource_key(res)
            if key is None:
                # Keep "weird" resources rather than silently dropping them,
                # but don't attempt to de-dupe them.
                merged.append(res)
                continue

            if key in seen:
                continue  # first-wins
            seen.add(key)
            merged.append(res)

    policy_doc = {"resources": merged}

    effective_hash = compute_effective_policy_hash(
        policy_id=None,
        policy_name="effective",
        schema_version=None,
        mode=mode,
        document=policy_doc,
        sources=sources,
    )

    return PolicySnapshot(
        mode=mode,
        policy=policy_doc,
        meta={
            "device_id": str(device_id),
            "device_key": device_key,
            "assignments": len(rows),
            "sources": sources,
            "effective_hash": effective_hash,
        },
    )
